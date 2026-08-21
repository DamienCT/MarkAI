"use client";

import React from "react";
import { toast } from "sonner";
import {
  CheckCircle2, Search, Target, FileText, Zap,
  Loader2, Rocket, Clock, Eye, RefreshCw, ArrowRight,
  TrendingUp, Play, Square,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import type { Brand, Content, EngagementMetrics, AgentRun, Channel } from "@/types";

interface ChannelConfig {
  enabled: boolean;
  configured: boolean;
  [key: string]: unknown;
}

const CHANNEL_ICON_STYLED: Record<string, { icon: React.ReactNode; color: string }> = {
  instagram: { icon: <span className="h-4 w-4 inline-block" />, color: "bg-linear-to-br from-purple-500 via-pink-500 to-orange-400 text-white" },
  facebook: { icon: <span className="h-4 w-4 inline-block" />, color: "bg-[#1877F2] text-white" },
  linkedin: { icon: <span className="h-4 w-4 inline-block" />, color: "bg-[#0A66C2] text-white" },
  youtube: { icon: <span className="h-4 w-4 inline-block" />, color: "bg-[#FF0000] text-white" },
  tiktok: { icon: <span className="h-4 w-4 inline-block" />, color: "bg-black text-white dark:bg-white dark:text-black" },
  x: { icon: <span className="h-4 w-4 inline-block" />, color: "bg-black text-white dark:bg-white dark:text-black" },
  website_blog: { icon: <span className="h-4 w-4 inline-block" />, color: "bg-emerald-600 text-white" },
  teams: { icon: <span className="h-4 w-4 inline-block" />, color: "bg-[#6264A7] text-white" },
};

// We accept the styled icons from the parent so we get proper lucide icons
export interface OverviewTabProps {
  brand: Brand;
  content: Content[];
  metrics: EngagementMetrics | null;
  channelConfigs: Record<string, ChannelConfig>;
  channelIconStyled: Record<string, { icon: React.ReactNode; color: string }>;
  channelDisplayNames: Record<Channel, string>;
  enabledChannels: [string, ChannelConfig][];
  pipelineRuns: AgentRun[];
  loadingPipeline: boolean;
  togglingFactory: boolean;
  onboardingProgress: { completed: number; total: number; isComplete: boolean; loaded?: boolean };
  onOpenOnboarding: () => void;
  onToggleContentFactory: (turnOn: boolean) => Promise<void>;
  onGenerateContent: () => Promise<void>;
  generatingContent: boolean;
  contentItemsQueued: number;
  contentStats: { generated: number; failed: number; in_progress: number; total: number; working?: number };
  onFetchPipelineRuns: () => Promise<void>;
  onSetActiveTab: (tab: string) => void;
  onFetchIntelligence: () => void;
  research: { id: string; agent_type: string; status: string; completed_at?: string; output_payload?: Record<string, unknown> }[];
}

export function OverviewTab({
  brand,
  metrics,
  channelConfigs,
  channelIconStyled,
  channelDisplayNames,
  enabledChannels,
  pipelineRuns,
  loadingPipeline,
  togglingFactory,
  onboardingProgress,
  onOpenOnboarding,
  onToggleContentFactory,
  onGenerateContent,
  generatingContent,
  contentItemsQueued,
  contentStats,
  onFetchPipelineRuns,
  onSetActiveTab,
  onFetchIntelligence,
  research,
}: OverviewTabProps) {
  // 7-day window label (matches the backend NOW()→NOW()+7d count). Captured
  // once at mount via a lazy initializer — reading the clock during render
  // is impure (react-hooks/purity), and the label doesn't need to tick live.
  const [weekWindow] = React.useState(() => {
    const fmtDay = (d: Date) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const now = new Date();
    return {
      start: fmtDay(now),
      end: fmtDay(new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000)),
    };
  });
  return (
    <div className="space-y-6 mt-6">
      {/* Onboarding Progress Card — only render once async data is loaded to prevent flicker */}
      {onboardingProgress.loaded !== false && (
        <button
          type="button"
          onClick={onOpenOnboarding}
          className={`w-full text-left rounded-lg border p-4 transition-colors hover:bg-accent/50 ${
            onboardingProgress.isComplete
              ? "border-muted bg-muted/30 opacity-60 hover:opacity-80"
              : "border-primary/30 bg-primary/5"
          }`}
        >
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className={`flex items-center justify-center h-9 w-9 rounded-full shrink-0 ${
                onboardingProgress.isComplete ? "bg-green-100 dark:bg-green-900/30" : "bg-primary/10"
              }`}>
                {onboardingProgress.isComplete ? (
                  <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
                ) : (
                  <Rocket className="h-5 w-5 text-primary" />
                )}
              </div>
              <div className="min-w-0">
                <p className={`text-sm font-medium ${onboardingProgress.isComplete ? "text-muted-foreground" : ""}`}>
                  {onboardingProgress.isComplete ? "Setup Complete" : "Brand Setup"}
                </p>
                <p className="text-xs text-muted-foreground">
                  {onboardingProgress.completed}/{onboardingProgress.total} steps completed
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <div className="w-32 h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    onboardingProgress.isComplete ? "bg-green-500" : "bg-primary"
                  }`}
                  style={{ width: `${Math.round((onboardingProgress.completed / onboardingProgress.total) * 100)}%` }}
                />
              </div>
              <span className={`text-xs font-medium tabular-nums ${
                onboardingProgress.isComplete ? "text-green-600 dark:text-green-400" : "text-primary"
              }`}>
                {Math.round((onboardingProgress.completed / onboardingProgress.total) * 100)}%
              </span>
            </div>
          </div>
        </button>
      )}

      {/* Agent Pipeline Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg">Context Generation</CardTitle>
              <CardDescription>Automated research, strategy, planning, and calendar strategy</CardDescription>
            </div>
            <div className="flex items-center gap-3">
              {/* Quick jump to Intelligence tab once all 4 context reports
                  are done — replaces the per-stage View Report links. */}
              {(() => {
                const REPORT_AGENT_TYPES = ["research", "strategy", "planning", "content_calendar"] as const;
                const REPORT_ALT: Record<string, string> = { content_calendar: "content_calendar_strategy" };
                const allDone = REPORT_AGENT_TYPES.every((t) => {
                  const direct = pipelineRuns.find((r) => r.agent_type === t && r.status === "completed");
                  if (direct) return true;
                  const altKey = REPORT_ALT[t];
                  return !!(altKey && pipelineRuns.find((r) => r.agent_type === altKey && r.status === "completed"));
                });
                if (!allDone) return null;
                return (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      onSetActiveTab("intelligence");
                      if (research.length === 0) onFetchIntelligence();
                    }}
                  >
                    <Eye className="mr-1.5 h-4 w-4" />
                    View Report
                  </Button>
                );
              })()}
              {(() => {
                if (brand.status === 'onboarding') {
                  return (
                    <span className={`text-sm ${onboardingProgress.isComplete ? "text-green-600 dark:text-green-400" : "text-orange-600 dark:text-orange-400"}`}>
                      Status: {onboardingProgress.isComplete ? "Ready to activate" : "Setup Required"}
                    </span>
                  );
                }
                if (brand.status === 'activating') {
                  // Only consider runs from current activation
                  const activationStart = brand.activation_started_at
                    ? new Date(brand.activation_started_at).getTime() - 5000
                    : 0;
                  const currentActivationRuns = pipelineRuns.filter(r => {
                    const runStart = r.started_at ? new Date(r.started_at).getTime() : 0;
                    return runStart >= activationStart;
                  });
                  const runningRun = currentActivationRuns.find((r) => r.status === "running");
                  const completedCount = currentActivationRuns.filter((r) => r.status === "completed").length;
                  const failedRun = currentActivationRuns.find((r) => r.status === "failed");
                  const statusDetail = runningRun
                    ? `Running ${runningRun.agent_type}...`
                    : failedRun
                    ? `${failedRun.agent_type} failed`
                    : completedCount > 0
                    ? `${completedCount} stage${completedCount !== 1 ? "s" : ""} done`
                    : "Starting up...";
                  return (
                    <span className={`text-sm flex items-center gap-1.5 ${
                      failedRun ? "text-red-600 dark:text-red-400" : "text-blue-600 dark:text-blue-400"
                    }`}>
                      {!failedRun && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                      Status: {statusDetail}
                    </span>
                  );
                }
                const runningRun = pipelineRuns.find((r) => r.status === "running");
                const statusText = !brand.is_active
                  ? "Idle"
                  : runningRun
                  ? `Running ${runningRun.agent_type}...`
                  : "Active";
                return (
                  <span className={`text-sm ${brand.is_active ? "text-green-600 dark:text-green-400" : "text-muted-foreground"}`}>
                    Status: {statusText}
                  </span>
                );
              })()}
              {brand.status === 'onboarding' && !onboardingProgress.isComplete ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled
                >
                  <Play className="mr-1.5 h-4 w-4" />
                  Run Context Generation
                </Button>
              ) : brand.status === 'onboarding' && onboardingProgress.isComplete ? (
                <Button
                  size="sm"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white dark:bg-emerald-700 dark:hover:bg-emerald-600"
                  disabled={togglingFactory}
                  onClick={() => onToggleContentFactory(true)}
                >
                  {togglingFactory ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-1.5 h-4 w-4" />
                  )}
                  Run Context Generation
                </Button>
              ) : brand.status === 'activating' ? (
                (() => {
                  // Only consider runs from current activation (filter out old runs)
                  const activationStart = brand.activation_started_at
                    ? new Date(brand.activation_started_at).getTime() - 5000
                    : 0;
                  const currentRuns = pipelineRuns.filter(r => {
                    const runStart = r.started_at ? new Date(r.started_at).getTime() : 0;
                    return runStart >= activationStart;
                  });
                  const hasFailed = currentRuns.some(r => r.status === "failed");
                  const hasRunning = currentRuns.some(r => r.status === "running");
                  if (hasFailed && !hasRunning) {
                    return (
                      <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white dark:bg-emerald-700 dark:hover:bg-emerald-600"
                        disabled={togglingFactory} onClick={() => onToggleContentFactory(true)}>
                        {togglingFactory ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Play className="mr-1.5 h-4 w-4" />}
                        Retry Context Generation
                      </Button>
                    );
                  }
                  return (
                    <Button size="sm" variant="destructive"
                      disabled={togglingFactory} onClick={() => onToggleContentFactory(false)}>
                      {togglingFactory ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Square className="mr-1.5 h-4 w-4" />}
                      Stop Context Generation
                    </Button>
                  );
                })()
              ) : brand.is_active ? (
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={togglingFactory}
                  onClick={() => onToggleContentFactory(false)}
                >
                  {togglingFactory ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Square className="mr-1.5 h-4 w-4" />
                  )}
                  Stop Context Generation
                </Button>
              ) : (
                <Button
                  size="sm"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white dark:bg-emerald-700 dark:hover:bg-emerald-600"
                  disabled={togglingFactory}
                  onClick={() => onToggleContentFactory(true)}
                >
                  {togglingFactory ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-1.5 h-4 w-4" />
                  )}
                  Run Context Generation
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {brand.status === 'onboarding' && !onboardingProgress.isComplete && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Rocket className="h-10 w-10 text-orange-500 mb-3" />
              <p className="text-sm font-medium">Complete setup to run Context Generation</p>
              <p className="text-xs text-muted-foreground mt-1">
                Finish the required onboarding steps, then activate to begin automated research, strategy, and planning.
              </p>
            </div>
          )}
          {brand.status === 'onboarding' && onboardingProgress.isComplete && pipelineRuns.length === 0 && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Rocket className="h-10 w-10 text-green-500 mb-3" />
              <p className="text-sm font-medium">Ready to run Context Generation</p>
              <p className="text-xs text-muted-foreground mt-1">
                Setup is complete. Click Run Context Generation above to begin automated research, strategy, and planning.
              </p>
            </div>
          )}
          {(brand.status !== 'onboarding' || pipelineRuns.length > 0) && (() => {
            // Report stages (produce Intelligence documents)
            const REPORT_STAGES = [
              { key: "research", label: "Research", icon: <Search className="h-6 w-6" /> },
              { key: "strategy", label: "Strategy", icon: <Target className="h-6 w-6" /> },
              { key: "planning", label: "Marketing Plan", icon: <FileText className="h-6 w-6" /> },
              { key: "content_calendar", label: "Calendar Strategy", icon: <FileText className="h-6 w-6" />, altKey: "content_calendar_strategy" },
            ] as const;

            const latestByType: Record<string, AgentRun> = {};
            for (const run of pipelineRuns) {
              const t = run.agent_type;
              if (!latestByType[t] || new Date(run.created_at) > new Date(latestByType[t].created_at)) {
                latestByType[t] = run;
              }
            }

            // Content generation stats from calendar items in 7-day window
            const contentCompleted = contentStats.generated;
            // "Running" = an item is actively being generated (status 'working'),
            // NOT merely sitting in 'queued'. Items in 'queued' must keep the
            // Generate Content button ENABLED so they can be processed — otherwise
            // queued-but-stalled items deadlock the button.
            const contentRunning = (contentStats.working ?? 0) > 0;
            const contentFailed = contentStats.failed;
            const contentTotal = contentStats.total;
            // 7-day window dates: weekWindow, captured at mount (see above)
            const allReportsDone = REPORT_STAGES.every(s => {
              const r = latestByType[s.key] || (("altKey" in s && s.altKey) ? latestByType[s.altKey] : undefined);
              return r?.status === "completed";
            });

            const statusBadgeClass = (status: string | undefined) => {
              if (!status) return "bg-muted text-muted-foreground";
              switch (status) {
                case "completed": return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300";
                case "running": return "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300";
                case "failed": return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300";
                case "cancelled": return "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300";
                default: return "bg-muted text-muted-foreground";
              }
            };

            return (
              <div className="space-y-4">
                {/* Report Pipeline Stages */}
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Intelligence Reports</p>
                <div className="flex items-start justify-between gap-0 overflow-x-auto pb-2">
                  {REPORT_STAGES.map((stage, idx) => {
                    // Check both primary key and altKey for content_calendar/content_calendar_strategy
                    const run = latestByType[stage.key] || (("altKey" in stage && stage.altKey) ? latestByType[stage.altKey] : undefined);
                    const status = run?.status || "pending";
                    return (
                      <React.Fragment key={stage.key}>
                        <div className="flex flex-col items-center flex-1 min-w-[120px] px-1">
                          <div className={`flex items-center justify-center h-14 w-14 rounded-full border-2 transition-colors ${
                            status === "completed" ? "border-green-500 bg-green-50 dark:bg-green-900/30 text-green-600" :
                            status === "running" ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-600" :
                            status === "failed" ? "border-red-500 bg-red-50 dark:bg-red-900/30 text-red-600" :
                            status === "cancelled" ? "border-orange-500 bg-orange-50 dark:bg-orange-900/30 text-orange-600" :
                            "border-muted-foreground/30 bg-muted/30 text-muted-foreground"
                          }`}>
                            {status === "running" ? <Loader2 className="h-6 w-6 animate-spin" /> : stage.icon}
                          </div>
                          <p className="text-sm font-medium mt-2 text-center">{stage.label}</p>
                          <Badge variant="outline" className={`text-xs mt-1 ${statusBadgeClass(status)}`}>
                            {status}
                          </Badge>
                          {run?.completed_at && (
                            <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {formatRelativeTime(run.completed_at)}
                            </p>
                          )}
                        </div>
                        {idx < REPORT_STAGES.length - 1 && (
                          <div className="flex items-center pt-5 shrink-0">
                            <ArrowRight className={`h-5 w-5 ${
                              latestByType[REPORT_STAGES[idx + 1].key]?.status === "completed" ||
                              latestByType[REPORT_STAGES[idx + 1].key]?.status === "running"
                                ? "text-primary" : "text-muted-foreground/30"
                            }`} />
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>

                {/* Content Generation (Step 2 — separate from Context Generation) */}
                <div className="border-t pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Content Generation</p>
                    {(() => {
                      // First-time approval gate: if context_approvals exist and
                      // first_approval_completed is false, the button stays clickable
                      // but the handler shows a toast instead of triggering the API,
                      // so the user gets feedback ("approve the reports first")
                      // rather than a silent disabled state.
                      const guidelines = (brand.brand_guidelines as Record<string, unknown> | undefined) || {};
                      const approvals = guidelines.context_approvals as Record<string, string> | undefined;
                      const firstDone = guidelines.first_approval_completed === true;
                      const gateActive = !!approvals && !firstDone;
                      const allApproved = approvals
                        ? ["research", "strategy", "planning", "calendar"].every(
                            (d) => approvals[d] === "approved"
                          )
                        : true;
                      const blockedByGate = gateActive && !allApproved;
                      const hardDisabled = !allReportsDone || generatingContent || !!contentRunning;
                      const visuallyDisabled = hardDisabled || blockedByGate;
                      return (
                        <Button
                          size="sm"
                          className={`bg-blue-600 hover:bg-blue-700 text-white dark:bg-blue-700 dark:hover:bg-blue-600 ${
                            visuallyDisabled ? "opacity-50 cursor-not-allowed hover:bg-blue-600 dark:hover:bg-blue-700" : ""
                          }`}
                          disabled={hardDisabled}
                          onClick={() => {
                            if (blockedByGate) {
                              toast.error(
                                "You must review and approve all 4 reports before generating content."
                              );
                              onSetActiveTab("intelligence");
                              if (research.length === 0) onFetchIntelligence();
                              return;
                            }
                            onGenerateContent();
                          }}
                        >
                          {generatingContent ? (
                            <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                          ) : (
                            <Zap className="mr-1.5 h-4 w-4" />
                          )}
                          Generate Content
                        </Button>
                      );
                    })()}
                  </div>
                  {(() => {
                    const isGenerating = !!contentRunning || (contentItemsQueued > 0 && contentCompleted < contentItemsQueued);
                    // Denominator: prefer the just-queued count (fresh from Generate Content),
                    // otherwise derive from DB-backed stats so reloads don't show "X of 0".
                    const statsTotal = contentCompleted + contentStats.in_progress + contentFailed;
                    const totalItems = contentItemsQueued > 0 ? contentItemsQueued : statsTotal;
                    return (
                      <div className="flex items-center gap-3">
                        <div className={`flex items-center justify-center h-10 w-10 rounded-full border-2 transition-colors ${
                          isGenerating ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-600" :
                          contentFailed > 0 ? "border-red-500 bg-red-50 dark:bg-red-900/30 text-red-600" :
                          contentCompleted > 0 ? "border-green-500 bg-green-50 dark:bg-green-900/30 text-green-600" :
                          "border-muted-foreground/30 bg-muted/30 text-muted-foreground"
                        }`}>
                          {isGenerating ? <Loader2 className="h-5 w-5 animate-spin" /> : <Zap className="h-5 w-5" />}
                        </div>
                        <div className="flex-1">
                          {isGenerating ? (
                            <div>
                              <p className="text-sm text-blue-600 dark:text-blue-400 flex items-center gap-1.5">
                                <span>Generating content...</span>
                              </p>
                              <p className="text-xs text-muted-foreground mt-0.5">
                                {contentCompleted} of {totalItems} items completed{contentFailed > 0 ? ` · ${contentFailed} failed` : ""}
                              </p>
                            </div>
                          ) : contentTotal === 0 && contentItemsQueued === 0 ? (
                            <p className="text-sm text-muted-foreground">
                              {allReportsDone ? "Ready — click Generate Content to start" : "Complete Context Generation first"}
                            </p>
                          ) : (
                            <p className="text-sm">
                              <span className="font-medium">{contentCompleted}</span>
                              <span className="text-muted-foreground">
                                {contentTotal > 0 ? ` of ${contentTotal}` : ""} post{contentCompleted !== 1 ? "s" : ""} generated this week ({weekWindow.start} – {weekWindow.end})
                              </span>
                              {contentFailed > 0 && (
                                <span className="text-red-500 ml-1">({contentFailed} failed)</span>
                              )}
                            </p>
                          )}
                        </div>
                      </div>
                    );
                  })()}
                </div>

                {loadingPipeline && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" /> Loading pipeline status...
                  </div>
                )}
                <div className="flex items-center gap-2 pt-2 border-t">
                  <Button size="sm" variant="outline" onClick={onFetchPipelineRuns} disabled={loadingPipeline}>
                    <RefreshCw className={`mr-1 h-3 w-3 ${loadingPipeline ? "animate-spin" : ""}`} />
                    Refresh Status
                  </Button>
                </div>
              </div>
            );
          })()}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <p className="text-sm text-muted-foreground">Description</p>
              <p className="text-sm">{brand.description || "No description"}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Created</p>
              <p className="text-sm">{formatDate(brand.created_at)}</p>
            </div>
            {/* Brand Colors */}
            {(() => {
              const palette = brand.color_palette as { primary?: string; secondary?: string; accent?: string } | undefined;
              if (!palette?.primary && !palette?.secondary && !palette?.accent) return null;
              return (
                <div>
                  <p className="text-sm text-muted-foreground mb-2">Brand Colors</p>
                  <div className="flex items-center gap-3">
                    {([
                      { key: "primary" as const, label: "Primary" },
                      { key: "secondary" as const, label: "Secondary" },
                      { key: "accent" as const, label: "Accent" },
                    ] as const).map(({ key, label }) => {
                      const hex = palette?.[key];
                      if (!hex) return null;
                      return (
                        <div key={key} className="flex items-center gap-1.5" title={`${label}: ${hex}`}>
                          <span
                            className="inline-block h-5 w-5 rounded-full border border-border shadow-sm"
                            style={{ backgroundColor: hex }}
                          />
                          <span className="text-xs font-mono text-muted-foreground uppercase">{hex}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Performance</CardTitle>
          </CardHeader>
          <CardContent>
            {metrics ? (
              <div className="space-y-2">
                <div className="rounded-lg border p-4 text-center">
                  <p className="text-3xl font-bold">{metrics.reach.toLocaleString()}</p>
                  <p className="text-sm text-muted-foreground">Reach</p>
                </div>
                <div className="rounded-lg border p-4 text-center">
                  <p className="text-3xl font-bold">{metrics.impressions.toLocaleString()}</p>
                  <p className="text-sm text-muted-foreground">Impressions</p>
                </div>
                <div className="rounded-lg border p-4 text-center">
                  <p className="text-3xl font-bold">{(metrics.engagement_rate * 100).toFixed(2)}%</p>
                  <p className="text-sm text-muted-foreground">Engagement Rate</p>
                </div>
                <div className="rounded-lg border p-4 text-center">
                  <p className="text-3xl font-bold">{metrics.shares.toLocaleString()}</p>
                  <p className="text-sm text-muted-foreground">Shares</p>
                </div>
              </div>
            ) : (
              <div className="text-center py-2">
                <TrendingUp className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
                <p className="text-sm text-muted-foreground">No engagement data yet</p>
                <p className="text-xs text-muted-foreground mt-0.5">Metrics appear after content is published</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Channels</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
              {Object.entries(channelIconStyled).map(([ch, style]) => {
                const cfg = channelConfigs[ch];
                const isEnabled = cfg?.enabled;
                const isConfigured = cfg?.configured;
                let className = "bg-muted/50 text-muted-foreground/30";
                if (isEnabled && isConfigured) className = style.color;
                else if (isEnabled) className = "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400";
                return (
                  <div key={ch} className="flex flex-col items-center gap-1.5">
                    <span
                      className={`flex items-center justify-center h-11 w-11 rounded-lg [&>svg]:h-5 [&>svg]:w-5 ${className}`}
                      title={`${channelDisplayNames[ch as Channel]} - ${isEnabled && isConfigured ? "active" : isEnabled ? "needs setup" : "disabled"}`}
                    >
                      {style.icon}
                    </span>
                    <span className={`text-[11px] text-center leading-tight ${isEnabled ? "text-foreground" : "text-muted-foreground/50"}`}>
                      {channelDisplayNames[ch as Channel]}
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground mt-3">
              {enabledChannels.length} channel{enabledChannels.length !== 1 ? "s" : ""} enabled
            </p>

            {/* BC Integration — mirrors Edit Brand → Business Central */}
            <div className="mt-5 pt-4 border-t">
              <h3 className="text-lg font-semibold leading-none tracking-tight mb-3">
                BC Integration
              </h3>
              {brand.bc_company ? (
                <dl className="text-sm space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-muted-foreground">Company</dt>
                    <dd className="font-medium text-right">{brand.bc_company}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <dt className="text-muted-foreground">Locations</dt>
                    <dd className="text-right">
                      {brand.bc_locations && brand.bc_locations.length > 0
                        ? brand.bc_locations.join(", ")
                        : "None selected"}
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">Not linked to Business Central</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
