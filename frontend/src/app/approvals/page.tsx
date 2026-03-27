"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ApprovalActions } from "@/components/approval/ApprovalActions";
import { api } from "@/lib/api";
import { formatRelativeTime, statusColor } from "@/lib/utils";
import type { Approval } from "@/types";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApprovals();
  }, []);

  async function fetchApprovals() {
    setLoading(true);
    try {
      const data = await api.get<Approval[]>("/api/v1/approvals", { status: "pending" });
      setApprovals(data);
    } catch {
      toast.error("Failed to load approvals");
    } finally {
      setLoading(false);
    }
  }

  const handleAction = async (approvalId: string, action: "approved" | "rejected", comments: string) => {
    try {
      await api.put(`/api/v1/approvals/${approvalId}`, { status: action, comments });
      setApprovals((prev) => prev.filter((a) => a.id !== approvalId));
      toast.success(`Content ${action}`);
      // Refetch to sync counts
      fetchApprovals();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || `Failed to ${action === "approved" ? "approve" : "reject"} content`;
      toast.error(detail);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Approvals</h1>
        <p className="text-muted-foreground">Review and approve pending content</p>
      </div>

      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-48" />
          ))}
        </div>
      ) : approvals.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-lg text-muted-foreground">No pending approvals</p>
            <p className="text-sm text-muted-foreground mt-1">All caught up!</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {approvals.map((approval) => (
            <Card key={approval.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-lg">
                      {approval.content?.title || `Content #${approval.content_id}`}
                    </CardTitle>
                    <CardDescription>
                      {approval.content?.platform && (
                        <span className="capitalize">{approval.content.platform}</span>
                      )}
                      {" - "}
                      Submitted {formatRelativeTime(approval.created_at)}
                    </CardDescription>
                  </div>
                  <Badge className={statusColor(approval.status)}>{approval.status}</Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {approval.content && (
                  <div className="rounded-md border p-4">
                    <p className="text-sm whitespace-pre-wrap">{approval.content.caption}</p>
                    {approval.content.hashtags && approval.content.hashtags.length > 0 && (
                      <p className="text-sm text-primary mt-2">
                        {approval.content.hashtags.map((h: string) => `#${h}`).join(" ")}
                      </p>
                    )}
                  </div>
                )}
                <ApprovalActions
                  approvalId={approval.id}
                  onAction={handleAction}
                />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
