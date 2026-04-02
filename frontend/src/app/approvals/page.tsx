"use client";

import React, { useEffect, useState, useMemo } from "react";
import { toast } from "sonner";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ChannelPreview } from "@/components/content/ChannelPreview";
import { ApprovalActions } from "@/components/approval/ApprovalActions";
import { api } from "@/lib/api";
import { useRequireRole } from "@/lib/hooks";
import { formatRelativeTime, statusColor } from "@/lib/utils";
import type { Approval, Brand } from "@/types";

interface ApprovalWithExtra extends Approval {
  calendar_item_id?: string;
  calendar_item?: {
    title?: string;
    channel?: string;
    scheduled_at?: string;
  };
}

export default function ApprovalsPage() {
  const { hasAccess, loading: roleLoading } = useRequireRole("editor");
  const [approvals, setApprovals] = useState<ApprovalWithExtra[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(true);
  const [brandFilter, setBrandFilter] = useState<string>("all");
  const [channelFilter, setChannelFilter] = useState<string>("all");

  useEffect(() => {
    fetchApprovals();
    api.get<Brand[]>("/api/v1/brands").then(setBrands).catch(() => {});
  }, []);

  async function fetchApprovals() {
    setLoading(true);
    try {
      const data = await api.get<{ items: ApprovalWithExtra[] } | ApprovalWithExtra[]>("/api/v1/approvals", { status: "pending" });
      setApprovals(Array.isArray(data) ? data : (data as { items: ApprovalWithExtra[] }).items || []);
    } catch {
      toast.error("Failed to load approvals");
    } finally {
      setLoading(false);
    }
  }

  const handleAction = async (approvalId: string, action: "approved" | "rejected", comments: string) => {
    try {
      await api.put(`/api/v1/approvals/${approvalId}`, { status: action, feedback: comments });
      setApprovals((prev) => prev.filter((a) => a.id !== approvalId));
      toast.success(`Content ${action}`);
      fetchApprovals();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || `Failed to ${action === "approved" ? "approve" : "reject"} content`;
      toast.error(detail);
    }
  };

  // Derive unique channels from data
  const channels = useMemo(() => {
    const set = new Set<string>();
    approvals.forEach(a => {
      const ch = a.calendar_item?.channel;
      if (ch) set.add(ch);
    });
    return Array.from(set).sort();
  }, [approvals]);

  // Filter approvals
  const filtered = useMemo(() => {
    return approvals.filter(a => {
      if (brandFilter !== "all" && a.content?.brand_id !== brandFilter) return false;
      if (channelFilter !== "all" && a.calendar_item?.channel !== channelFilter) return false;
      return true;
    });
  }, [approvals, brandFilter, channelFilter]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold">Approvals</h1>
          <p className="text-muted-foreground">Review and approve pending content</p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={brandFilter} onValueChange={setBrandFilter}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="All Brands" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Brands</SelectItem>
              {brands.map(b => (
                <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={channelFilter} onValueChange={setChannelFilter}>
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="All Channels" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Channels</SelectItem>
              {channels.map(ch => (
                <SelectItem key={ch} value={ch} className="capitalize">{ch}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-48" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-lg text-muted-foreground">No pending approvals</p>
            <p className="text-sm text-muted-foreground mt-1">
              {approvals.length > 0 ? "No items match the selected filters" : "All caught up!"}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {filtered.map((approval) => {
            const channel = approval.calendar_item?.channel || "instagram";
            const title = approval.calendar_item?.title || approval.content?.headline || `Content #${approval.content_id?.substring(0, 8)}`;
            const caption = approval.content?.caption || "";
            const hashtags = Array.isArray(approval.content?.hashtags) ? approval.content.hashtags : [];
            const brandName = approval.content?.brand_name || "Brand";

            return (
              <Card key={approval.id} className="overflow-hidden">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <CardTitle className="text-sm truncate">
                        <Link href={`/content/${approval.calendar_item_id || approval.content_id}`} className="hover:underline">
                          {title}
                        </Link>
                      </CardTitle>
                      <CardDescription className="flex items-center gap-2 mt-1">
                        <Badge variant="outline" className="text-[10px] capitalize">{channel}</Badge>
                        <span className="text-xs">Submitted {formatRelativeTime(approval.created_at)}</span>
                      </CardDescription>
                    </div>
                    <Badge className={statusColor(approval.status)} variant="outline">{approval.status}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="relative max-h-[300px] overflow-hidden rounded-lg">
                    <ChannelPreview
                      channel={channel}
                      brandName={brandName}
                      brandHandle={brandName.toLowerCase().replace(/\s+/g, "")}
                      caption={caption}
                      hashtags={hashtags}
                      compact
                    />
                    <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-card to-transparent pointer-events-none" />
                  </div>
                  <ApprovalActions
                    approvalId={approval.id}
                    onAction={handleAction}
                  />
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
