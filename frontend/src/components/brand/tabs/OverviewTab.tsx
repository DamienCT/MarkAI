"use client";

import React from "react";
import {
  CheckCircle2, Search, Target, FileText, Calendar, Zap,
  Loader2, Rocket, Clock, Eye, RefreshCw, ArrowRight,
  TrendingUp, Play, Square,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { statusColor, formatDate, formatRelativeTime } from "@/lib/utils";
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
  onboardingProgress: { completed: number; total: number; isComplete: boolean };
  onOpenOnboarding: () => void;
  onToggleContentFactory: (turnOn: boolean) => Promise<void>;
  onFetchPipelineRuns: () => Promise<void>;
  onSetActiveTab: (tab: string) => void;
  onFetchIntelligence: () => void;
  research: { id: string; agent_type: string; status: string; completed_at?: string; output_payload?: Record<string, unknown> }[];
}

export function OverviewTab({
  brand,
  content,
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
  onFetchPipelineRuns,
  onSetActiveTab,
  onFetchIntelligence,
  research,
}: OverviewTabProps) {
  return (
    <div className="space-y-6 mt-6">
      {/* Onboarding Progress Card */}
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

      {/* Agent Pipeline Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg">Content Factory</CardTitle>
              <CardDescription>Automated research, strategy, planning, and content generation</CardDescription>
            </div>
            <div className="flex items-center gap-3">
              {(() => {
                if (brand.status === 'onboarding') {
                  return (
                    <span className={`text-sm ${onboardingProgress.isComplete ? "text-green-600 dark:text-green-400" : "text-orange-600 dark:text-orange-400"}`}>
                      Status: {onboardingProgress.isComplete ? "Ready to activate" : "Setup Required"}
                    </span>
                  );
                }
                if (brand.status === 'activating') {
                  const runningRun = pipelineRuns.find((r) => r.status === "running");
                  const completedCount = pipelineRuns.filter((r) => r.status === "completed").length;
                  const statusDetail = runningRun
                    ? `Running ${runningRun.agent_type}...`
                    : completedCount > 0
                    ? `${completedCount} stage${completedCount !== 1 ? "s" : ""} done`
                    : "Setting up...";
                  return (
                    <span className="text-sm text-blue-600 dark:text-blue-400 flex items-center gap-1.5">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
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
                  Start Content Factory
                </Button>
              ) : brand.status === 'onboarding' && onboardingProgress.isComplete ? (
                <Button
                  size="sm"
                  className="bg-green-600 hover:bg-green-700 text-white"
                  disabled={togglingFactory}
                  onClick={() => onToggleContentFactory(true)}
                >
                  {togglingFactory ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-1.5 h-4 w-4" />
                  )}
                  Start Content Factory
                </Button>
              ) : brand.status === 'activating' ? (
                <div className="flex items-center gap-2">
                  {pipelineRuns.some(r => r.status === "failed") ? (
                    <Button
                      size="sm"
                      className="bg-green-600 hover:bg-green-700 text-white"
                      disabled={togglingFactory}
                      onClick={() => onToggleContentFactory(true)}
                    >
                      {togglingFactory ? (
                        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="mr-1.5 h-4 w-4" />
                      )}
                      Retry Content Factory
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled
                    >
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                      Setting up...
                    </Button>
                  )}
                </div>
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
                  Stop Content Factory
                </Button>
              ) : (
                <Button
                  size="sm"
                  className="bg-green-600 hover:bg-green-700 text-white"
                  disabled={togglingFactory}
                  onClick={() => onToggleContentFactory(true)}
                >
                  {togglingFactory ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-1.5 h-4 w-4" />
                  )}
                  Start Content Factory
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {brand.status === 'onboarding' && !onboardingProgress.isComplete && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Rocket className="h-10 w-10 text-orange-500 mb-3" />
              <p className="text-sm font-medium">Complete setup to start your Content Factory</p>
              <p className="text-xs text-muted-foreground mt-1">
                Finish the required onboarding steps, then activate to begin automated content generation.
              </p>
            </div>
          )}
          {brand.status === 'onboarding' && onboardingProgress.isComplete && pipelineRuns.length === 0 && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Rocket className="h-10 w-10 text-green-500 mb-3" />
              <p className="text-sm font-medium">Ready to launch your Content Factory</p>
              <p className="text-xs text-muted-foreground mt-1">
                Setup is complete. Click Start Content Factory above to begin automated content generation.
              </p>
            </div>
          )}
          {(brand.status !== 'onboarding' || pipelineRuns.length > 0) && (() => {
            const PIPELINE_STAGES = [
              { key: "research", label: "Research", icon: <Search className="h-6 w-6" /> },
              { key: "strategy", label: "Strategy", icon: <Target className="h-6 w-6" /> },
              { key: "planning", label: "Marketing Plan", icon: <FileText className="h-6 w-6" /> },
              { key: "content_calendar", label: "Content Calendar", icon: <Calendar className="h-6 w-6" /> },
              { key: "content", label: "Content Generation", icon: <Zap className="h-6 w-6" /> },
            ] as const;

            const latestByType: Record<string, AgentRun> = {};
            for (const run of pipelineRuns) {
              const t = run.agent_type;
              if (!latestByType[t] || new Date(run.created_at) > new Date(latestByType[t].created_at)) {
                latestByType[t] = run;
              }
            }

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
                <div className="flex items-start justify-between gap-0 overflow-x-auto pb-2">
                  {PIPELINE_STAGES.map((stage, idx) => {
                    const run = latestByType[stage.key];
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
                          {run?.status === "completed" && (
                            <Button
                              variant="link"
                              size="sm"
                              className="h-auto p-0 text-xs mt-1"
                              onClick={() => {
                                onSetActiveTab("intelligence");
                                if (research.length === 0) onFetchIntelligence();
                              }}
                            >
                              <Eye className="mr-1 h-3 w-3" /> View Report
                            </Button>
                          )}
                        </div>
                        {idx < PIPELINE_STAGES.length - 1 && (
                          <div className="flex items-center pt-5 shrink-0">
                            <ArrowRight className={`h-5 w-5 ${
                              latestByType[PIPELINE_STAGES[idx + 1].key]?.status === "completed" ||
                              latestByType[PIPELINE_STAGES[idx + 1].key]?.status === "running"
                                ? "text-primary" : "text-muted-foreground/30"
                            }`} />
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })}
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
              <p className="text-sm text-muted-foreground">BC Company</p>
              <p className="text-sm">{brand.bc_company || "Not linked"}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Created</p>
              <p className="text-sm">{formatDate(brand.created_at)}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Engagement</CardTitle>
          </CardHeader>
          <CardContent>
            {metrics ? (
              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-sm text-muted-foreground">Impressions</span>
                  <span className="text-sm font-medium">{metrics.impressions.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-muted-foreground">Engagement Rate</span>
                  <span className="text-sm font-medium">{(metrics.engagement_rate * 100).toFixed(2)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-muted-foreground">Likes</span>
                  <span className="text-sm font-medium">{metrics.likes.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-muted-foreground">Comments</span>
                  <span className="text-sm font-medium">{metrics.comments.toLocaleString()}</span>
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
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(channelIconStyled).map(([ch, style]) => {
                const cfg = channelConfigs[ch];
                const isEnabled = cfg?.enabled;
                const isConfigured = cfg?.configured;
                let className = "bg-muted/50 text-muted-foreground/30";
                if (isEnabled && isConfigured) className = style.color;
                else if (isEnabled) className = "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400";
                return (
                  <span
                    key={ch}
                    className={`flex items-center justify-center h-7 w-7 rounded-md ${className}`}
                    title={`${channelDisplayNames[ch as Channel]} - ${isEnabled && isConfigured ? "active" : isEnabled ? "needs setup" : "disabled"}`}
                  >
                    {style.icon}
                  </span>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              {enabledChannels.length} channel{enabledChannels.length !== 1 ? "s" : ""} enabled
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent Content</CardTitle>
          <CardDescription>Latest content for this brand</CardDescription>
        </CardHeader>
        <CardContent>
          {content.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">No content yet</p>
          ) : (
            <div className="space-y-2">
              {content.slice(0, 5).map((item) => (
                <div key={item.id} className="flex items-center justify-between rounded-md border p-3">
                  <div>
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="text-xs text-muted-foreground">{item.platform} - {formatDate(item.created_at)}</p>
                  </div>
                  <Badge className={statusColor(item.status)} variant="outline">
                    {item.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
