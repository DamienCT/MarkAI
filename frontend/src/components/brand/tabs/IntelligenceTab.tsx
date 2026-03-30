"use client";

import React from "react";
import {
  Search, Target, FileText, Calendar, Zap, Eye,
  RotateCcw, Loader2,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/utils";

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
}

export function IntelligenceTab({
  research,
  competitors,
  loadingIntel,
  triggeringWorkflow,
  onTriggerWorkflow,
}: IntelligenceTabProps) {
  const router = useRouter();

  return (
    <div className="mt-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Brand Intelligence</h2>
        <p className="text-sm text-muted-foreground">AI-generated documents and insights for this brand</p>
      </div>

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
              { agent_type: "content_calendar", title: "Content Calendar", icon: <Calendar className="h-5 w-5" />, triggerKey: "planning", pipelineOrder: 3 },
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
                        <CardTitle className="text-base">{doc.title}</CardTitle>
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
                    {hasOutput ? (
                      <div className="flex items-center justify-between">
                        <Button
                          variant="default"
                          size="sm"
                          onClick={() => router.push(`/intelligence/report/${run.id}`)}
                        >
                          <Eye className="mr-1.5 h-3.5 w-3.5" />
                          View Full Report
                        </Button>
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
                      </div>
                    ) : isRunning ? (
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
          <CardTitle className="text-base">Discovered Competitors</CardTitle>
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
