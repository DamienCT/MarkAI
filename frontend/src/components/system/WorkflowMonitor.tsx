"use client";

import React from "react";
import { Activity } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { statusColor, formatRelativeTime } from "@/lib/utils";
import type { AgentRun } from "@/types";

interface WorkflowMonitorProps {
  runs: AgentRun[];
}

export function WorkflowMonitor({ runs }: WorkflowMonitorProps) {
  if (runs.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        No recent workflow runs
      </p>
    );
  }

  return (
    <div className="space-y-2 max-h-[400px] overflow-y-auto">
      {runs.map((run) => (
        <div key={run.id} className="flex items-center justify-between rounded-md border p-3">
          <div className="flex items-center gap-3">
            <Activity className="h-4 w-4 text-muted-foreground shrink-0" />
            <div>
              <p className="text-sm font-medium">{run.agent_type}</p>
              <p className="text-xs text-muted-foreground">
                {run.started_at ? formatRelativeTime(run.started_at) : formatRelativeTime(run.created_at)}
                {run.duration_seconds !== undefined && run.duration_seconds !== null && (
                  <span> - {run.duration_seconds.toFixed(1)}s</span>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {run.error_message && (
              <span className="text-xs text-destructive max-w-[200px] truncate" title={run.error_message}>
                {run.error_message}
              </span>
            )}
            <Badge className={statusColor(run.status)} variant="outline">
              {run.status}
            </Badge>
          </div>
        </div>
      ))}
    </div>
  );
}
