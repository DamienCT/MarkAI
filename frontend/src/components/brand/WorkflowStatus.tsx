"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Activity, CheckCircle2, XCircle, Loader2, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";

interface AgentRun {
  id: string;
  agent_type: string;
  status: string;
  started_at: string;
  completed_at?: string;
  error_message?: string;
}

interface WorkflowStatusProps {
  brandId: string;
  /** If set, only show runs of this type */
  filterType?: string;
  /** Auto-start polling when mounted */
  autoPolling?: boolean;
}

export function WorkflowStatus({ brandId, filterType, autoPolling = true }: WorkflowStatusProps) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [polling, setPolling] = useState(autoPolling);

  const fetchRuns = useCallback(async () => {
    try {
      const data = await api.get<AgentRun[]>("/api/v1/agents/runs", {
        brand_id: brandId,
        limit: 5,
      });
      const filtered = filterType
        ? data.filter((r) => r.agent_type === filterType)
        : data;
      setRuns(filtered);
    } catch {
      // Silently fail
    }
  }, [brandId, filterType]);

  useEffect(() => {
    fetchRuns();
    if (!polling) return;
    const interval = setInterval(fetchRuns, 5000);
    return () => clearInterval(interval);
  }, [fetchRuns, polling]);

  // Stop polling if no running jobs
  useEffect(() => {
    const hasRunning = runs.some((r) => r.status === "running" || r.status === "pending");
    if (!hasRunning && polling && runs.length > 0) {
      setPolling(false);
    }
  }, [runs, polling]);

  if (runs.length === 0) return null;

  const latestRun = runs[0];
  const isRunning = latestRun?.status === "running" || latestRun?.status === "pending";
  const isFailed = latestRun?.status === "failed";
  const isComplete = latestRun?.status === "completed";

  return (
    <div className="rounded-lg border bg-card text-card-foreground">
      <button
        type="button"
        className="flex items-center justify-between w-full px-3 py-2 text-xs hover:bg-muted/50 transition-colors rounded-lg"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          {isRunning ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
          ) : isFailed ? (
            <XCircle className="h-3.5 w-3.5 text-red-500" />
          ) : isComplete ? (
            <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
          ) : (
            <Activity className="h-3.5 w-3.5 text-muted-foreground" />
          )}
          <span className="font-medium">
            {isRunning ? "Workflow running..." : `Last run: ${latestRun?.agent_type}`}
          </span>
          <Badge
            variant={isRunning ? "default" : isFailed ? "destructive" : "secondary"}
            className="text-[10px] h-4"
          >
            {latestRun?.status}
          </Badge>
          {latestRun?.started_at && (
            <span className="text-muted-foreground">
              {formatRelativeTime(latestRun.started_at)}
            </span>
          )}
        </div>
        <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="px-3 pb-2 space-y-1.5 border-t pt-2">
          {runs.map((run) => (
            <div key={run.id} className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                {run.status === "running" || run.status === "pending" ? (
                  <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
                ) : run.status === "failed" ? (
                  <XCircle className="h-3 w-3 text-red-500" />
                ) : (
                  <CheckCircle2 className="h-3 w-3 text-green-500" />
                )}
                <span className="capitalize">{run.agent_type}</span>
                <Badge variant="outline" className="text-[9px] h-3.5">
                  {run.status}
                </Badge>
              </div>
              <span className="text-muted-foreground">
                {run.started_at ? formatRelativeTime(run.started_at) : ""}
              </span>
            </div>
          ))}
          {runs.some((r) => r.status === "failed" && r.error_message) && (
            <div className="mt-1 p-2 rounded-sm bg-red-50 dark:bg-red-950/30 text-xs text-red-700 dark:text-red-300">
              {runs.find((r) => r.status === "failed")?.error_message}
            </div>
          )}
          {!polling && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-[10px] w-full"
              onClick={() => { setPolling(true); fetchRuns(); }}
            >
              Refresh
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
