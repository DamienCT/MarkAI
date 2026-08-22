"use client";

import React, { useEffect, useState, useMemo } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ChannelPreview } from "@/components/content/ChannelPreview";
import { ApprovalActions } from "@/components/approval/ApprovalActions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RefreshCw, X } from "lucide-react";
import { format } from "date-fns";
import { api, fileUrl, isAuthError } from "@/lib/api";
import { getStoredBrandValue } from "@/lib/brand-selection";
import { useRequireRole } from "@/lib/hooks";
import { formatDateTime, formatRelativeTime, statusColor } from "@/lib/utils";
import type { Approval } from "@/types";

interface ApprovalWithExtra extends Approval {
  calendar_item_id?: string;
  calendar_item?: {
    title?: string;
    channel?: string;
    scheduled_at?: string;
  };
}

// Agent runs paused mid-workflow for a human decision — the shape returned
// by GET /api/v1/agents/runs/paused.
interface PausedAgentRun {
  id: string;
  workflow_type: string;
  brand_id: string | null;
  brand_name: string | null;
  trigger?: string | null;
  created_at: string;
  paused_at: string | null;
  interrupt: {
    type: string | null;
    message: string | null;
    interrupt_id: string | null;
    count: number;
  };
}

export default function ApprovalsPage() {
  useRequireRole("editor"); // redirects unauthorized users as a side effect
  const { data: session } = useSession();
  const [approvals, setApprovals] = useState<ApprovalWithExtra[]>([]);
  const [loading, setLoading] = useState(true);
  const [channelFilter, setChannelFilter] = useState<string>("all");
  const [dateFilter, setDateFilter] = useState<string>("");
  const [brandFilter, setBrandFilter] = useState<string>("all");
  const [pausedRuns, setPausedRuns] = useState<PausedAgentRun[]>([]);
  const [reviewingRunId, setReviewingRunId] = useState<string | null>(null);
  const [rejectingRunId, setRejectingRunId] = useState<string | null>(null);
  const [rejectFeedback, setRejectFeedback] = useState("");

  // Run reviews are manager/admin only server-side — hide the buttons below
  // that (same gate as the learning page's decision buttons).
  const userRole =
    (session?.user as Record<string, unknown> | undefined)?.role as string | undefined;
  const canDecide = userRole === "manager" || userRole === "admin";

  useEffect(() => {
    fetchApprovals();
    fetchPausedRuns();
  }, []);

  // Follow the global sidebar brand selection: hydrate from localStorage after
  // mount (client-only, avoids SSR mismatch) and update when it changes.
  useEffect(() => {
    setBrandFilter(getStoredBrandValue());
    const handler = (e: Event) => {
      const brandId = (e as CustomEvent).detail?.brandId;
      setBrandFilter(brandId || "all");
    };
    window.addEventListener("brand-changed", handler);
    return () => window.removeEventListener("brand-changed", handler);
  }, []);

  async function fetchApprovals() {
    setLoading(true);
    try {
      const data = await api.get<{ items: ApprovalWithExtra[] } | ApprovalWithExtra[]>("/api/v1/approvals", { status: "pending" });
      setApprovals(Array.isArray(data) ? data : (data as { items: ApprovalWithExtra[] }).items || []);
    } catch (err) {
      // Session expiry: the sign-in redirect is already underway.
      if (!isAuthError(err)) toast.error("Failed to load approvals");
    } finally {
      setLoading(false);
    }
  }

  async function fetchPausedRuns() {
    try {
      const data = await api.get<PausedAgentRun[]>("/api/v1/agents/runs/paused");
      setPausedRuns(data);
    } catch (err) {
      // Session expiry: the sign-in redirect is already underway.
      if (!isAuthError(err)) toast.error("Failed to load pending agent reviews");
    }
  }

  const handleRunReview = async (runId: string, action: "approve" | "reject") => {
    const feedback = action === "reject" ? rejectFeedback.trim() : "";
    if (action === "reject" && !feedback) {
      toast.error("Rejection feedback is required");
      return;
    }
    setReviewingRunId(runId);
    try {
      await api.post<{ status: string }>(`/api/v1/agents/runs/${runId}/review`, {
        action,
        ...(feedback ? { feedback } : {}),
      });
      // 202 accepted: the worker picks the resume up asynchronously — the row
      // stays paused_for_review in the DB until it does, so drop it locally
      // instead of refetching it straight back. If the resume message is ever
      // lost, the run reappears on the next refresh and a second click is safe.
      setPausedRuns((prev) => prev.filter((r) => r.id !== runId));
      setRejectingRunId(null);
      setRejectFeedback("");
      toast.success(
        action === "approve"
          ? "Run approved — resuming"
          : "Run rejected — the agent will revise"
      );
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || `Failed to ${action} the run`;
      toast.error(detail);
    } finally {
      setReviewingRunId(null);
    }
  };

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
      if (dateFilter) {
        const scheduled = a.calendar_item?.scheduled_at;
        if (!scheduled) return false;
        if (format(new Date(scheduled), "yyyy-MM-dd") !== dateFilter) return false;
      }
      return true;
    });
  }, [approvals, brandFilter, channelFilter, dateFilter]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold">Approvals</h1>
          <p className="text-muted-foreground">Review and approve pending content</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            <Input
              type="date"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              className="w-[170px]"
              aria-label="Filter by publish date"
            />
            {dateFilter && (
              <Button
                variant="ghost"
                size="sm"
                className="h-9 w-9 p-0"
                onClick={() => setDateFilter("")}
                aria-label="Clear date filter"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
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

      {/* Pending agent reviews — workflows paused mid-run for a human decision */}
      {pausedRuns.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <div>
                <CardTitle>Pending Agent Reviews</CardTitle>
                <CardDescription>
                  Workflows paused mid-run, waiting for a human decision
                </CardDescription>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-9 w-9 p-0"
                onClick={fetchPausedRuns}
                aria-label="Refresh pending agent reviews"
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {pausedRuns.map((run) => (
              <div key={run.id} className="rounded-md border p-3 space-y-2">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium capitalize">
                      {run.workflow_type} workflow
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {run.brand_name || "No brand"}
                      {" · paused "}
                      {formatRelativeTime(run.paused_at || run.created_at)}
                    </p>
                  </div>
                  <Badge className={statusColor("in_review")} variant="outline">
                    needs review
                  </Badge>
                </div>
                {run.interrupt.message && (
                  <p className="text-xs text-muted-foreground">{run.interrupt.message}</p>
                )}
                {canDecide &&
                  (rejectingRunId === run.id ? (
                    <div className="flex items-center gap-2 flex-wrap">
                      <Input
                        value={rejectFeedback}
                        onChange={(e) => setRejectFeedback(e.target.value)}
                        placeholder="Why is this rejected? The agent revises with this feedback."
                        className="h-8 text-xs flex-1 min-w-[220px]"
                        aria-label="Rejection feedback"
                      />
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={reviewingRunId === run.id || !rejectFeedback.trim()}
                        onClick={() => handleRunReview(run.id, "reject")}
                      >
                        Confirm Reject
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setRejectingRunId(null);
                          setRejectFeedback("");
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={reviewingRunId === run.id}
                        onClick={() => {
                          setRejectingRunId(run.id);
                          setRejectFeedback("");
                        }}
                      >
                        Reject
                      </Button>
                      <Button
                        size="sm"
                        disabled={reviewingRunId === run.id}
                        onClick={() => handleRunReview(run.id, "approve")}
                      >
                        Approve
                      </Button>
                    </div>
                  ))}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

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
            // Resolve the generated media — prefer branded (logo+text) over raw,
            // same priority as the content detail page.
            const gm = (approval.content?.generation_metadata || {}) as Record<string, unknown>;
            const imagePath = (gm.branded_image || gm.raw_image || gm.generated_image_url || "") as string;
            const fullImageUrl = imagePath ? fileUrl(imagePath) : "";
            // Grid thumbnail: 800px wide, quality 75 — same on-the-fly resize
            // params PlatformMockups uses, so cards don't pull full-size originals.
            const imageUrl = fullImageUrl
              ? fullImageUrl.includes("?")
                ? `${fullImageUrl}&w=800&q=75`
                : `${fullImageUrl}?w=800&q=75`
              : undefined;
            const videoUrl = approval.content?.video_url ? fileUrl(approval.content.video_url) : undefined;

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
                      <CardDescription className="flex items-center flex-wrap gap-2 mt-1">
                        <Badge variant="outline" className="text-[10px] capitalize">{channel}</Badge>
                        <span className="text-xs">Submitted {formatRelativeTime(approval.created_at)}</span>
                        {approval.calendar_item?.scheduled_at && (
                          <span className="text-xs">
                            · Publishes {formatDateTime(approval.calendar_item.scheduled_at)}
                          </span>
                        )}
                      </CardDescription>
                    </div>
                    <Badge className={statusColor(approval.status)} variant="outline">{approval.status}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {/* Reels get a taller window so the 9:16 player + controls stay usable */}
                  <div className={`relative ${videoUrl ? "max-h-[460px]" : "max-h-[300px]"} overflow-hidden rounded-lg`}>
                    <ChannelPreview
                      channel={channel}
                      brandName={brandName}
                      brandHandle={brandName.toLowerCase().replace(/\s+/g, "")}
                      caption={caption}
                      hashtags={hashtags}
                      imageUrl={imageUrl}
                      videoUrl={videoUrl}
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
