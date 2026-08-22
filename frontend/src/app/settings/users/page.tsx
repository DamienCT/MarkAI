"use client";

import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, isAuthError } from "@/lib/api";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import { useRequireRole } from "@/lib/hooks";


interface UserFromAPI {
  id: string;
  email: string;
  display_name: string;
  entra_id: string;
  avatar_url: string | null;
  role: "admin" | "manager" | "editor" | "viewer";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

interface EntraUser {
  id: string;
  displayName: string;
  mail: string | null;
  userPrincipalName: string | null;
}

interface GrantAccessResult {
  granted: string[];
  errors: string[];
}

export default function UsersPage() {
  useRequireRole("admin"); // redirects unauthorized users as a side effect
  const [users, setUsers] = useState<UserFromAPI[]>([]);
  const [loading, setLoading] = useState(true);
  const [securityGroupMembers, setSecurityGroupMembers] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<EntraUser[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [grantRole, setGrantRole] = useState<string>("viewer");
  const [granting, setGranting] = useState(false);

  const fetchUsers = useCallback(async () => {
    try {
      const data = await api.get<UserFromAPI[]>("/api/v1/users");
      setUsers(data);
    } catch (err) {
      // Session expiry: the sign-in redirect is already underway.
      if (!isAuthError(err)) toast.error("Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchSecurityGroupMembers = useCallback(async () => {
    try {
      const members = await api.get<string[]>("/api/v1/users/security-group-members");
      setSecurityGroupMembers(new Set(members));
    } catch {
      // Security group check is optional
    }
  }, []);

  useEffect(() => {
    fetchUsers();
    fetchSecurityGroupMembers();
  }, [fetchUsers, fetchSecurityGroupMembers]);

  useEffect(() => {
    if (!searchQuery || searchQuery.length < 2) {
      setSearchResults([]);
      return;
    }

    const timeout = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await api.get<EntraUser[]>("/api/v1/users/search", { q: searchQuery });
        setSearchResults(results);
      } catch {
        setSearchResults([]);
        toast.error("Search failed");
      } finally {
        setSearching(false);
      }
    }, 400);

    return () => clearTimeout(timeout);
  }, [searchQuery]);

  const toggleSelection = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleGrantAccess = async () => {
    if (selectedIds.size === 0) {
      toast.error("Select at least one user");
      return;
    }
    setGranting(true);
    try {
      const result = await api.post<GrantAccessResult>("/api/v1/users/grant-access", {
        user_ids: Array.from(selectedIds),
        role: grantRole,
      });
      if (result.granted.length > 0) {
        toast.success(`Access granted to ${result.granted.length} user${result.granted.length !== 1 ? "s" : ""}`);
      }
      if (result.errors.length > 0) {
        toast.warning(`${result.errors.length} user${result.errors.length !== 1 ? "s" : ""} could not be added`);
      }
      setSelectedIds(new Set());
      setSearchQuery("");
      setSearchResults([]);
      await fetchUsers();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to grant access";
      toast.error(detail);
    } finally {
      setGranting(false);
    }
  };

  const handleRoleChange = async (userId: string, role: string) => {
    try {
      await api.patch(`/api/v1/users/${userId}`, { role });
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, role: role as UserFromAPI["role"] } : u))
      );
      toast.success("Role updated");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update role";
      toast.error(detail);
    }
  };

  const handleToggleActive = async (userId: string, isActive: boolean) => {
    try {
      await api.patch(`/api/v1/users/${userId}`, { is_active: !isActive });
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, is_active: !isActive } : u))
      );
      toast.success(isActive ? "User deactivated" : "User activated");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update user status";
      toast.error(detail);
    }
  };

  const isSecurityGroupMember = (user: UserFromAPI): boolean => {
    return securityGroupMembers.has(user.entra_id);
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Users & Roles</h1>
        <Skeleton className="h-96" />
      </div>
    );
  }

  const existingEntraIds = new Set(users.map((u) => u.entra_id));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Users & Roles</h1>
        <p className="text-muted-foreground">Manage user access and permissions</p>
      </div>

      {/* Search & Grant Access */}
      <Card>
        <CardHeader>
          <CardTitle>Add Users from Microsoft Entra ID</CardTitle>
          <CardDescription>Search for users in your organization and grant them access to MARKAI</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input
            placeholder="Search by name or email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />

          {searching && <p className="text-sm text-muted-foreground">Searching...</p>}

          {searchResults.length > 0 && (
            <div className="border rounded-md max-h-64 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10"></TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead className="text-center">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {searchResults.map((result) => {
                    const alreadyExists = existingEntraIds.has(result.id);
                    const isSelected = selectedIds.has(result.id);
                    return (
                      <TableRow
                        key={result.id}
                        className={isSelected ? "bg-accent" : "cursor-pointer hover:bg-accent/50"}
                        onClick={() => !alreadyExists && toggleSelection(result.id)}
                      >
                        <TableCell>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            disabled={alreadyExists}
                            onChange={(e) => { e.stopPropagation(); toggleSelection(result.id); }}
                            onClick={(e) => e.stopPropagation()}
                            className="h-4 w-4 rounded-sm border-input cursor-pointer"
                          />
                        </TableCell>
                        <TableCell className="font-medium">{result.displayName}</TableCell>
                        <TableCell className="text-sm">{result.mail || result.userPrincipalName || "--"}</TableCell>
                        <TableCell className="text-center">
                          {alreadyExists ? (
                            <Badge variant="outline">Already Added</Badge>
                          ) : securityGroupMembers.has(result.id) ? (
                            <Badge className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">Security Group</Badge>
                          ) : (
                            <span className="text-sm text-muted-foreground">Available</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {selectedIds.size > 0 && (
            <div className="flex items-center gap-3 pt-2">
              <span className="text-sm font-medium">
                {selectedIds.size} user{selectedIds.size !== 1 ? "s" : ""} selected
              </span>
              <Select value={grantRole} onValueChange={setGrantRole}>
                <SelectTrigger className="w-[130px] h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">Admin</SelectItem>
                  <SelectItem value="manager">Manager</SelectItem>
                  <SelectItem value="editor">Editor</SelectItem>
                  <SelectItem value="viewer">Viewer</SelectItem>
                </SelectContent>
              </Select>
              <Button onClick={handleGrantAccess} disabled={granting} size="sm">
                {granting ? "Granting..." : "Grant Access"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Existing Users Table */}
      <Card>
        <CardHeader>
          <CardTitle>Team Members</CardTitle>
          <CardDescription>{users.length} users registered</CardDescription>
        </CardHeader>
        <CardContent>
          {users.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No users found</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Login</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Avatar className="h-8 w-8">
                          <AvatarImage src={user.avatar_url || undefined} />
                          <AvatarFallback>
                            {user.display_name.split(" ").map((n) => n[0]).join("").toUpperCase()}
                          </AvatarFallback>
                        </Avatar>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{user.display_name}</span>
                          {isSecurityGroupMember(user) && (
                            <Badge variant="secondary" className="text-xs">Security Group</Badge>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">{user.email}</TableCell>
                    <TableCell>
                      <Select value={user.role} onValueChange={(val) => handleRoleChange(user.id, val)}>
                        <SelectTrigger className="w-[120px] h-8">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="admin">Admin</SelectItem>
                          <SelectItem value="manager">Manager</SelectItem>
                          <SelectItem value="editor">Editor</SelectItem>
                          <SelectItem value="viewer">Viewer</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_active ? "default" : "outline"}>
                        {user.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {user.last_login_at ? formatRelativeTime(user.last_login_at) : "Never"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(user.created_at)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleToggleActive(user.id, user.is_active)}
                      >
                        {user.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
