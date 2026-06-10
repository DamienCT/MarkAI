"use client";

import React, { useEffect, useState } from "react";
import {
  Search, Target, FileText, Calendar, Zap, Eye,
  RotateCcw, Loader2, AlertTriangle, Check, Pencil,
} from "lucide-react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/utils";
import { api } from "@/lib/api";
import { EditDocumentsModal } from "@/components/brand/EditDocumentsModal";

// Doc-card cardKey → context_approvals key in brand.brand_guidelines.
// content_calendar maps to "calendar" because that's how the backend stores it.
const APPROVAL_KEY_BY_AGENT_TYPE: Record<string, string> = {
  research: "research",
  strategy: "strategy",
  planning: "planning",
  content_calendar: "calendar",
};

interface ResearchReport {
  id: string;
  brand_id?: string;
  agent_type: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  output_payload?: Record<string, unknown>;
}

interface CompetitorData {
  id: string;
  name: string;
  website_url?: string;
  social_handles: Record<string, string>;
  notes?: string;
}

export interface IntelligenceTabProps {
  research: ResearchReport[];
  competitors: CompetitorData[];
  loadingIntel: boolean;
  triggeringWorkflow: string | null;
  onTriggerWorkflow: (workflowType: string) => Promise<void>;
  brandId?: string;
  /**
   * First-time approval gate state. When `gateActive` is true (i.e.
   * context_approvals exist on the brand and first_approval_completed is
   * false), each doc card shows Approve / Rework instead of the regular
   * Regenerate button until all four are approved. Once the gate closes
   * the buttons disappear permanently for this brand.
   */
  contextApprovals?: Record<string, string>;
  gateActive?: boolean;
  approvingDoc?: string | null;
  onApproveDoc?: (docType: string) => Promise<void>;
  onReworkDoc?: (docType: string, workflowType: string) => Promise<void>;
}

export function IntelligenceTab({
  research,
  competitors,
  loadingIntel,
  triggeringWorkflow,
  onTriggerWorkflow,
  brandId,
  contextApprovals,
  gateActive,
  approvingDoc,
  onApproveDoc,
  onReworkDoc,
}: IntelligenceTabProps) {
  const router = useRouter();
  const [eventsUpdatedAt, setEventsUpdatedAt] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchUpdatedAt() {
      try {
        const params = brandId ? { brand_id: brandId } : undefined;
        const resp = await api.get<{ updated_at: string | null }>(
          "/api/v1/events/updated-at",
          params
        );
        if (!cancelled) setEventsUpdatedAt(resp.updated_at);
      } catch {
        // non-fatal
      }
    }
    fetchUpdatedAt();
    return () => {
      cancelled = true;
    };
  }, [brandId, research]);

  const latestResearchRun = (() => {
    let latest: ResearchReport | undefined;
    for (const run of research) {
      if (run.agent_type !== "research") continue;
      if (run.status !== "completed") continue;
      if (!run.completed_at) continue;
      if (
        !latest ||
        !latest.completed_at ||
        new Date(run.completed_at) > new Date(latest.completed_at)
      ) {
        latest = run;
      }
    }
    return latest;
  })();

  const eventsStale =
    eventsUpdatedAt !== null &&
    latestResearchRun?.completed_at != null &&
    new Date(eventsUpdatedAt) > new Date(latestResearchRun.completed_at);

  return (
    <div className="mt-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Brand Intelligence</h2>
          <p className="text-sm text-muted-foreground">AI-generated documents and insights for this brand</p>
        </div>
        {brandId && (
          <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
            <Pencil className="mr-1.5 h-4 w-4" />
            Edit Documents
          </Button>
        )}
      </div>

      {brandId && (
        <EditDocumentsModal brandId={brandId} open={editOpen} onClose={() => setEditOpen(false)} />
      )}

      {eventsStale && (
        <div className="flex items-start gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            <p className="font-medium">
              Events updated since last research run
            </p>
            <p className="text-xs opacity-90">
              Rerun research to refresh the date-aware context used by strategy and calendar generation.
            </p>
          </div>
          <Link
            href="/events"
            className="text-xs font-medium underline underline-offset-2 shrink-0"
          >
            Review events
          </Link>
        </div>
      )}

      {loadingIntel ? (
        <div className="space-y-4">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {(() => {
            const DOC_TYPES = [
              { agent_type: "research", title: "Research Report", icon: <Search className="h-5 w-5" />, triggerKey: "research", pipelineOrder: 0 },
              { agent_type: "strategy", title: "Marketing Strategy", icon: <Target className="h-5 w-5" />, triggerKey: "strategy", pipelineOrder: 1 },
              { agent_type: "planning", title: "Marketing Plan", icon: <FileText className="h-5 w-5" />, triggerKey: "planning", pipelineOrder: 2 },
              { agent_type: "content_calendar", title: "Content Calendar Strategy", icon: <Calendar className="h-5 w-5" />, triggerKey: "planning", pipelineOrder: 3 },
            ] as const;

            const PIPELINE_ORDER: Record<string, number> = {
              research: 0,
              strategy: 1,
              planning: 2,
              content_calendar: 3,
              content: 4,
            };

            const latestByType: Record<string, ResearchReport> = {};
            for (const run of research) {
              const t = run.agent_type;
              if (!latestByType[t] || (run.started_at && (!latestByType[t].started_at || new Date(run.started_at) > new Date(latestByType[t].started_at)))) {
                latestByType[t] = run;
              }
            }

            const isEarlierStageRunning = (currentOrder: number): boolean => {
              return Object.entries(latestByType).some(([agentType, run]) => {
                const order = PIPELINE_ORDER[agentType] ?? -1;
                return order < currentOrder && run.status === "running";
              });
            };

            return DOC_TYPES.map((doc) => {
              const run = latestByType[doc.agent_type];
              const hasOutput = run?.status === "completed" && run.output_payload;
              const isRunning = run?.status === "running";
              const earlierRunning = isEarlierStageRunning(doc.pipelineOrder);
              const isDisabled = triggeringWorkflow !== null || isRunning || earlierRunning;

              return (
                <Card key={doc.agent_type}>
                  <CardHeader>
                    <div className="flex items-center gap-3">
                      <div className={`flex items-center justify-center h-10 w-10 rounded-lg ${
                        hasOutput
                          ? "bg-primary/10 text-primary"
                          : "bg-muted text-muted-foreground"
                      }`}>
                        {doc.icon}
                      </div>
                      <div className="flex-1">
                        <CardTitle className="text-lg">{doc.title}</CardTitle>
                        <CardDescription>
                          {hasOutput && run.completed_at
                            ? `Last updated ${formatRelativeTime(run.completed_at)}`
                            : "Not generated yet"}
                        </CardDescription>
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          run?.status === "completed"
                            ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300"
                            : run?.status === "running"
                            ? "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300"
                            : run?.status === "failed"
                            ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300"
                            : "bg-muted text-muted-foreground"
                        }
                      >
                        {run?.status || "pending"}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0">
                    {hasOutput ? (() => {
                      const approvalKey = APPROVAL_KEY_BY_AGENT_TYPE[doc.agent_type];
                      const docApproved = !!(approvalKey && contextApprovals?.[approvalKey] === "approved");
                      const showApprovalUI = !!gateActive && !!approvalKey && !!onApproveDoc && !!onReworkDoc;
                      const isApprovingThis = approvingDoc === approvalKey;
                      return (
                        <div className="flex items-center justify-between">
                          <Button
                            variant="default"
                            size="sm"
                            onClick={() => router.push(`/intelligence/report/${run.id}`)}
                          >
                            <Eye className="mr-1.5 h-3.5 w-3.5" />
                            View Full Report
                          </Button>
                          {showApprovalUI ? (
                            <div className="flex items-center gap-2">
                              {docApproved ? (
                                <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300">
                                  <Check className="mr-1 h-3 w-3" /> Approved
                                </Badge>
                              ) : (
                                <Button
                                  size="sm"
                                  className="bg-emerald-600 hover:bg-emerald-700 text-white dark:bg-emerald-700 dark:hover:bg-emerald-600"
                                  disabled={isApprovingThis || isDisabled}
                                  onClick={() => approvalKey && onApproveDoc(approvalKey)}
                                >
                                  {isApprovingThis ? (
                                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                  ) : (
                                    <Check className="mr-1 h-3 w-3" />
                                  )}
                                  Approve
                                </Button>
                              )}
                              <Button
                                size="sm"
                                variant="outline"
                                className="border-orange-400 text-orange-700 hover:bg-orange-50 dark:border-orange-700 dark:text-orange-300 dark:hover:bg-orange-950"
                                disabled={isDisabled}
                                onClick={() => approvalKey && onReworkDoc(approvalKey, doc.triggerKey)}
                                title={earlierRunning ? "Waiting for earlier pipeline stage" : undefined}
                              >
                                {triggeringWorkflow === doc.triggerKey ? (
                                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                ) : (
                                  <RotateCcw className="mr-1 h-3 w-3" />
                                )}
                                {earlierRunning ? "Waiting..." : "Rework"}
                              </Button>
                            </div>
                          ) : (
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={isDisabled}
                              onClick={() => onTriggerWorkflow(doc.triggerKey)}
                              title={earlierRunning ? "Waiting for earlier pipeline stage" : undefined}
                            >
                              {triggeringWorkflow === doc.triggerKey ? (
                                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              ) : (
                                <RotateCcw className="mr-1 h-3 w-3" />
                              )}
                              {earlierRunning ? "Waiting..." : "Regenerate"}
                            </Button>
                          )}
                        </div>
                      );
                    })() : isRunning ? (
                      <div className="flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span>Generating — this may take a minute...</span>
                      </div>
                    ) : earlierRunning ? (
                      <p className="text-sm text-muted-foreground flex items-center gap-2">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Waiting for earlier pipeline stage...
                      </p>
                    ) : run?.status === "failed" ? (
                      <div className="flex items-center justify-between">
                        <p className="text-sm text-red-500">Failed — click to retry</p>
                        <Button size="sm" variant="outline" disabled={isDisabled} onClick={() => onTriggerWorkflow(doc.triggerKey)}>
                          <RotateCcw className="mr-1 h-3 w-3" /> Retry
                        </Button>
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        disabled={isDisabled}
                        onClick={() => onTriggerWorkflow(doc.triggerKey)}
                      >
                        <Zap className="mr-1.5 h-3.5 w-3.5" />
                        Generate
                      </Button>
                    )}
                  </CardContent>
                </Card>
              );
            });
          })()}
        </div>
      )}

      {/* Competitors section below documents */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Discovered Competitors</CardTitle>
          <CardDescription>Competitors identified during research</CardDescription>
        </CardHeader>
        <CardContent>
          {competitors.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No competitors discovered yet. Run a research workflow to identify competitors.
            </p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {competitors.map((comp) => (
                <div key={comp.id} className="rounded-md border p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{comp.name}</span>
                    {comp.website_url && (
                      <a href={comp.website_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                        Visit
                      </a>
                    )}
                  </div>
                  {Object.keys(comp.social_handles || {}).length > 0 && (
                    <div className="flex gap-1 mt-1">
                      {Object.entries(comp.social_handles).map(([platform, handle]) => (
                        <Badge key={platform} variant="outline" className="text-[10px] capitalize">
                          {platform}: @{handle}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {comp.notes && (
                    <p className="text-xs text-muted-foreground mt-1">{comp.notes}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
