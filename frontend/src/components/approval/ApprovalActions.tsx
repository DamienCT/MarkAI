"use client";

import React, { useState } from "react";
import { CheckCircle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

interface ApprovalActionsProps {
  approvalId: string;
  onAction: (approvalId: string, action: "approved" | "rejected", comments: string) => Promise<void>;
}

export function ApprovalActions({ approvalId, onAction }: ApprovalActionsProps) {
  const [comments, setComments] = useState("");
  const [loading, setLoading] = useState(false);

  const handleAction = async (action: "approved" | "rejected") => {
    setLoading(true);
    try {
      await onAction(approvalId, action, comments);
      setComments("");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <Label htmlFor={`comments-${approvalId}`}>Comments</Label>
        <Textarea
          id={`comments-${approvalId}`}
          value={comments}
          onChange={(e) => setComments(e.target.value)}
          placeholder="Optional feedback or instructions..."
          rows={3}
        />
      </div>
      <div className="flex flex-col sm:flex-row gap-2 justify-end">
        <Button
          variant="outline"
          onClick={() => handleAction("rejected")}
          disabled={loading}
          className="text-destructive hover:text-destructive"
        >
          <XCircle className="mr-2 h-4 w-4" />
          Reject
        </Button>
        <Button onClick={() => handleAction("approved")} disabled={loading}>
          <CheckCircle className="mr-2 h-4 w-4" />
          Approve
        </Button>
      </div>
    </div>
  );
}
