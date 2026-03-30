"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { useRequireRole } from "@/lib/hooks";
import type { AuditLogEntry } from "@/types";

export default function AuditLogPage() {
  const { hasAccess, loading: roleLoading } = useRequireRole("manager");
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionFilter, setActionFilter] = useState<string>("all");
  const [resourceFilter, setResourceFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    fetchEntries();
  }, [actionFilter, resourceFilter, page]);

  async function fetchEntries() {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, limit: 50 };
      if (actionFilter !== "all") params.action = actionFilter;
      if (resourceFilter !== "all") params.resource_type = resourceFilter;
      if (searchQuery) params.search = searchQuery;
      const data = await api.get<AuditLogEntry[]>("/api/v1/audit", params);
      setEntries(data);
    } catch {
      toast.error("Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }

  const handleSearch = () => {
    setPage(1);
    fetchEntries();
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Audit Log</h1>
        <p className="text-muted-foreground">System activity and change tracking</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4">
            <div className="flex-1 min-w-[200px]">
              <Input
                placeholder="Search audit log..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              />
            </div>
            <Select value={actionFilter} onValueChange={setActionFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Action" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Actions</SelectItem>
                <SelectItem value="create">Create</SelectItem>
                <SelectItem value="update">Update</SelectItem>
                <SelectItem value="delete">Delete</SelectItem>
                <SelectItem value="approve">Approve</SelectItem>
                <SelectItem value="reject">Reject</SelectItem>
                <SelectItem value="publish">Publish</SelectItem>
              </SelectContent>
            </Select>
            <Select value={resourceFilter} onValueChange={setResourceFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Resource" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Resources</SelectItem>
                <SelectItem value="brand">Brand</SelectItem>
                <SelectItem value="content">Content</SelectItem>
                <SelectItem value="approval">Approval</SelectItem>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="prompt">Prompt</SelectItem>
                <SelectItem value="system">System</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={handleSearch}>Search</Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {loading ? (
            <Skeleton className="h-64" />
          ) : entries.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No audit log entries found</p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Resource</TableHead>
                    <TableHead>Resource ID</TableHead>
                    <TableHead>IP Address</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="text-sm">{formatDateTime(entry.created_at)}</TableCell>
                      <TableCell className="text-sm">{entry.user_name || entry.user_id || "System"}</TableCell>
                      <TableCell className="text-sm capitalize">{entry.action}</TableCell>
                      <TableCell className="text-sm capitalize">{entry.resource_type}</TableCell>
                      <TableCell className="text-sm font-mono text-xs">
                        {entry.resource_id ? entry.resource_id.substring(0, 8) + "..." : "N/A"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">{entry.ip_address || "N/A"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex justify-center gap-2 mt-4">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </Button>
                <span className="flex items-center text-sm text-muted-foreground">Page {page}</span>
                <Button variant="outline" size="sm" onClick={() => setPage((p) => p + 1)}>
                  Next
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
