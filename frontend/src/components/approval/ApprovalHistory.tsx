"use client";

import React from "react";
import { CheckCircle, XCircle, Clock, MessageSquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatRelativeTime, statusColor } from "@/lib/utils";
import type { Approval } from "@/types";

interface ApprovalHistoryProps {
  approvals: Approval[];
}

export function ApprovalHistory({ approvals }: ApprovalHistoryProps) {
  if (approvals.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-4">
        No approval history
      </p>
    );
  }

  const iconMap: Record<string, React.ReactNode> = {
    approved: <CheckCircle className="h-4 w-4 text-green-500" />,
    rejected: <XCircle className="h-4 w-4 text-red-500" />,
    pending: <Clock className="h-4 w-4 text-amber-500" />,
    revision_requested: <MessageSquare className="h-4 w-4 text-purple-500" />,
  };

  return (
    <div className="space-y-4">
      {approvals.map((approval, index) => (
        <div key={approval.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="flex h-8 w-8 items-center justify-center rounded-full border bg-background">
              {iconMap[approval.status] || <Clock className="h-4 w-4" />}
            </div>
            {index < approvals.length - 1 && (
              <div className="w-px flex-1 bg-border mt-1" />
            )}
          </div>
          <div className="flex-1 pb-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium">
                  {approval.reviewer_name || "System"}
                </p>
                <Badge className={statusColor(approval.status)} variant="outline">
                  {approval.status.replace("_", " ")}
                </Badge>
              </div>
              <span className="text-xs text-muted-foreground">
                {approval.decided_at
                  ? formatRelativeTime(approval.decided_at)
                  : formatRelativeTime(approval.created_at)}
              </span>
            </div>
            {approval.comments && (
              <p className="text-sm text-muted-foreground mt-1">{approval.comments}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
