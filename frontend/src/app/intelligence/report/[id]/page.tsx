"use client";

import React, { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { formatDate, formatDateTime, statusColor } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import ReactMarkdown from "react-markdown";
import { SafeValue, formatKeyValue } from "@/components/ui/safe-render";
import {
  ArrowLeft,
  Printer,
  Clock,
  Zap,
  AlertTriangle,
  Users,
  Target,
  TrendingUp,
  Globe,
  Share2,
  ExternalLink,
  BarChart3,
  Lightbulb,
  User,
  MapPin,
  DollarSign,
  Briefcase,
  Heart,
  ShoppingCart,
  FileText,
  Compass,
  CalendarDays,
  BookOpen,
  Megaphone,
  LayoutGrid,
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────

interface ReportData {
  id: string;
  agent_type: string;
  brand_id: string | null;
  brand_name: string | null;
  brand_description: string | null;
  brand_website: string | null;
  brand_industry: string | null;
  status: string;
  trigger: string;
  input_payload: Record<string, unknown> | null;
  output_payload: OutputPayload | null;
  error_message: string | null;
  tokens_used: number | null;
  cost_usd: number | null;
  duration_ms: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

interface OutputPayload {
  // Research fields
  gaps?: MarketGap[];
  personas?: Persona[];
  competitor_analysis?: CompetitorAnalysis[];
  competitor_urls?: string[];
  social_analysis?: SocialAnalysis;
  social_profiles?: SocialProfile[];
  errors?: string[];
  recommendations?: string[];
  // Strategy fields
  positioning?: string | Record<string, unknown>;
  brand_archetype?: string;
  emotional_territory?: string;
  competitive_differentiation?: { dimension?: string; brand?: string; competitors?: string }[];
  content_pillars?: ContentPillar[];
  target_audiences?: TargetAudience[];
  posting_cadence?: Record<string, unknown> | string;
  monthly_themes?: MonthlyTheme[];
  themes?: unknown[];
  // Planning fields
  campaigns?: Campaign[];
  calendar_summary?: string;
  calendar?: Record<string, unknown> | string;
  // Content calendar strategy fields
  strategy_document?: string;
  markdown?: string;
  content?: string;
  [key: string]: unknown;
}

interface ContentPillar {
  name?: string;
  title?: string;
  description?: string;
  topics?: string[];
  content_types?: string[];
  frequency?: string;
  audience_alignment?: string;
  seasonal_emphasis?: string;
  platform_fit?: string;
  visual_style?: string;
  pillar_rationale?: string;
}

interface TargetAudience {
  name?: string;
  segment?: string;
  description?: string;
  platforms?: string[];
  content_preferences?: string[];
}

interface MonthlyTheme {
  month?: string;
  theme?: string;
  name?: string;
  description?: string;
  focus_areas?: string[];
  campaigns?: string[];
}

interface Campaign {
  name?: string;
  title?: string;
  description?: string;
  start_date?: string;
  end_date?: string;
  channels?: string[];
  objectives?: string[];
  status?: string;
  budget?: string;
}

interface MarketGap {
  category?: string;
  title?: string;
  priority?: string;
  description?: string;
  opportunity?: string;
  recommendation?: string;
  tier?: string;
  confidence_score?: number;
  evidence?: string[];
  estimated_impact?: string;
  implementation_effort?: string;
  recommended_timeline?: string;
  target_audience?: string;
  success_metrics?: string[];
}

interface Persona {
  name?: string;
  demographics?: {
    age_range?: string;
    gender?: string;
    location?: string;
    income_level?: string;
    occupation?: string;
    education?: string;
  };
  psychographics?: {
    values?: string[];
    interests?: string[];
    lifestyle?: string;
    personality_traits?: string[];
  };
  preferred_platforms?: string[];
  pain_points?: string[];
  buying_triggers?: string[];
  content_preferences?: string[] | {
    formats?: string[];
    topics?: string[];
    tone?: string;
    language_mix?: string | Record<string, string>;
  };
  best_engagement_times?: string[];
  content_avoidance?: string[];
  description?: string;
}

interface CompetitorAnalysis {
  name?: string;
  website_url?: string;
  positioning?: string;
  strengths?: string[];
  weaknesses?: string[];
  social_presence?: Record<string, string>;
  content_strategy?: string;
  threat_level?: string;
  notes?: string;
}

interface SocialAnalysis {
  analysis?: string;
  platforms?: string[];
  summary?: string;
}

interface SocialProfile {
  platform?: string;
  handle?: string;
  url?: string;
  followers?: number;
}

// ── Priority helpers ─────────────────────────────────────────────────

function priorityColor(priority: string | undefined): string {
  if (!priority) return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";
  switch (priority.toLowerCase()) {
    case "high":
    case "critical":
      return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300";
    case "medium":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300";
    case "low":
      return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300";
    default:
      return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";
  }
}

function threatLevelColor(level: string | undefined): string {
  if (!level) return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";
  switch (level.toLowerCase()) {
    case "high":
    case "critical":
      return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300";
    case "medium":
      return "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300";
    case "low":
      return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300";
    default:
      return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";
  }
}

function formatDuration(ms: number | null): string {
  if (!ms) return "N/A";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

function formatAgentType(type: string): string {
  return type
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// ── Component ────────────────────────────────────────────────────────

export default function ReportPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;

  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchReport() {
      try {
        const data = await api.get<ReportData>(
          `/api/v1/intelligence/report/${runId}`
        );
        setReport(data);
      } catch (err: unknown) {
        const message =
          err && typeof err === "object" && "detail" in err
            ? (err as { detail: string }).detail
            : "Failed to load report";
        toast.error(message);
      } finally {
        setLoading(false);
      }
    }
    if (runId) fetchReport();
  }, [runId]);

  if (loading) {
    return (
      <div className="space-y-6 max-w-5xl mx-auto">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-6 w-96" />
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (!report) {
    return (
      <div className="flex flex-col items-center justify-center py-20 space-y-4">
        <AlertTriangle className="h-12 w-12 text-muted-foreground" />
        <h2 className="text-xl font-semibold">Report Not Found</h2>
        <p className="text-muted-foreground">
          The requested report could not be loaded.
        </p>
        <Button variant="outline" onClick={() => router.push("/intelligence")}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Intelligence
        </Button>
      </div>
    );
  }

  const output = report.output_payload || {};
  const agentType = report.agent_type;

  // Research fields
  const gaps = output.gaps || [];
  const personas = output.personas || [];
  const competitorAnalysis = output.competitor_analysis || [];
  const competitorUrls = output.competitor_urls || [];
  const socialAnalysis = output.social_analysis;
  const socialProfiles = output.social_profiles || [];
  const errors = output.errors || [];
  const recommendations = output.recommendations || [];

  // Strategy fields
  const positioning = output.positioning;
  const contentPillars = output.content_pillars || [];
  const targetAudiences = output.target_audiences || [];
  const postingCadence = output.posting_cadence;
  const monthlyThemes = output.monthly_themes || [];

  // Planning fields
  const campaigns = output.campaigns || [];
  const calendarSummary = output.calendar_summary || output.calendar;

  // Content calendar strategy fields
  const strategyDocument = output.strategy_document || output.markdown || output.content;

  // Executive summary stats
  const gapCount = gaps.length;
  const personaCount = personas.length;
  const competitorCount = competitorAnalysis.length;
  const highPriorityGaps = gaps.filter(
    (g) => g.priority?.toLowerCase() === "high" || g.priority?.toLowerCase() === "critical"
  ).length;

  const reportTitle = `${formatAgentType(report.agent_type)} Report${
    report.brand_name ? ` \u2014 ${report.brand_name}` : ""
  }`;

  const isResearch = agentType === "research";
  const isStrategy = agentType === "strategy";
  const isPlanning = agentType === "planning";
  const isContentCalendar = agentType === "content_calendar" || agentType === "content_calendar_strategy";

  return (
    <>

      <div className="space-y-8 max-w-5xl mx-auto pb-12">
        {/* ── Top Bar (no-print) ──────────────────────────────────── */}
        <div className="flex items-center justify-between no-print" data-no-print>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push("/intelligence")}
          >
            <ArrowLeft className="mr-2 h-4 w-4" /> Back to Intelligence
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => window.print()}
          >
            <Printer className="mr-2 h-4 w-4" /> Print Report
          </Button>
        </div>

        {/* ── Header ──────────────────────────────────────────────── */}
        <div className="space-y-3">
          <h1 className="text-3xl font-bold tracking-tight">{reportTitle}</h1>
          <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <Badge className={statusColor(report.status)}>
              {report.status}
            </Badge>
            <span className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              Generated {formatDateTime(report.created_at)}
            </span>
            {report.duration_ms && (
              <span className="flex items-center gap-1">
                <Zap className="h-3.5 w-3.5" />
                {formatDuration(report.duration_ms)}
              </span>
            )}
            {report.tokens_used && (
              <span className="text-xs">
                {report.tokens_used.toLocaleString()} tokens
              </span>
            )}
            {report.cost_usd != null && report.cost_usd > 0 && (
              <span className="text-xs">${report.cost_usd.toFixed(4)}</span>
            )}
          </div>
        </div>

        <Separator />

        {/* ── Executive Summary ────────────────────────────────────── */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-primary" />
              Executive Summary
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Research stats */}
            {isResearch && (
              <>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{gapCount}</p>
                    <p className="text-xs text-muted-foreground">Market Gaps</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{personaCount}</p>
                    <p className="text-xs text-muted-foreground">Personas</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{competitorCount}</p>
                    <p className="text-xs text-muted-foreground">Competitors</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-red-600">{highPriorityGaps}</p>
                    <p className="text-xs text-muted-foreground">High Priority</p>
                  </div>
                </div>
                {(gapCount > 0 || personaCount > 0 || competitorCount > 0) && (
                  <div className="space-y-2">
                    <h4 className="text-sm font-semibold">Key Findings</h4>
                    <ul className="space-y-1.5 text-sm text-muted-foreground">
                      {gapCount > 0 && (
                        <li className="flex items-start gap-2">
                          <Target className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                          <span>
                            Identified <strong>{gapCount}</strong> market gap{gapCount !== 1 ? "s" : ""}
                            {highPriorityGaps > 0 && (
                              <>, including <strong className="text-red-600">{highPriorityGaps}</strong> high-priority</>
                            )}
                          </span>
                        </li>
                      )}
                      {personaCount > 0 && (
                        <li className="flex items-start gap-2">
                          <Users className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                          <span>
                            Built <strong>{personaCount}</strong> audience persona{personaCount !== 1 ? "s" : ""} with detailed demographics and psychographics
                          </span>
                        </li>
                      )}
                      {competitorCount > 0 && (
                        <li className="flex items-start gap-2">
                          <TrendingUp className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                          <span>
                            Analyzed <strong>{competitorCount}</strong> competitor{competitorCount !== 1 ? "s" : ""}
                          </span>
                        </li>
                      )}
                      {socialAnalysis?.analysis && (
                        <li className="flex items-start gap-2">
                          <Share2 className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                          <span>Social media analysis completed</span>
                        </li>
                      )}
                    </ul>
                  </div>
                )}
              </>
            )}

            {/* Strategy stats */}
            {isStrategy && (
              <>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{contentPillars.length}</p>
                    <p className="text-xs text-muted-foreground">Content Pillars</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{targetAudiences.length}</p>
                    <p className="text-xs text-muted-foreground">Target Audiences</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{monthlyThemes.length}</p>
                    <p className="text-xs text-muted-foreground">Monthly Themes</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{positioning ? "1" : "0"}</p>
                    <p className="text-xs text-muted-foreground">Positioning</p>
                  </div>
                </div>
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">Strategy Overview</h4>
                  <ul className="space-y-1.5 text-sm text-muted-foreground">
                    {positioning && (
                      <li className="flex items-start gap-2">
                        <Compass className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                        <span>Brand positioning defined</span>
                      </li>
                    )}
                    {contentPillars.length > 0 && (
                      <li className="flex items-start gap-2">
                        <LayoutGrid className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                        <span><strong>{contentPillars.length}</strong> content pillar{contentPillars.length !== 1 ? "s" : ""} established</span>
                      </li>
                    )}
                    {postingCadence && (
                      <li className="flex items-start gap-2">
                        <CalendarDays className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                        <span>Posting cadence configured</span>
                      </li>
                    )}
                  </ul>
                </div>
              </>
            )}

            {/* Planning stats */}
            {isPlanning && (
              <>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{campaigns.length}</p>
                    <p className="text-xs text-muted-foreground">Campaigns</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{calendarSummary ? "1" : "0"}</p>
                    <p className="text-xs text-muted-foreground">Calendar</p>
                  </div>
                </div>
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">Plan Overview</h4>
                  <ul className="space-y-1.5 text-sm text-muted-foreground">
                    {campaigns.length > 0 && (
                      <li className="flex items-start gap-2">
                        <Megaphone className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                        <span><strong>{campaigns.length}</strong> campaign{campaigns.length !== 1 ? "s" : ""} planned</span>
                      </li>
                    )}
                    {calendarSummary && (
                      <li className="flex items-start gap-2">
                        <CalendarDays className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                        <span>Calendar summary available</span>
                      </li>
                    )}
                  </ul>
                </div>
              </>
            )}

            {/* Content Calendar Strategy stats */}
            {isContentCalendar && (
              <>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{monthlyThemes.length || 12}</p>
                    <p className="text-xs text-muted-foreground">Monthly Themes</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold text-primary">{strategyDocument ? "1" : "0"}</p>
                    <p className="text-xs text-muted-foreground">Strategy Doc</p>
                  </div>
                </div>
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">Content Calendar Overview</h4>
                  <ul className="space-y-1.5 text-sm text-muted-foreground">
                    {strategyDocument && (
                      <li className="flex items-start gap-2">
                        <BookOpen className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                        <span>Year-long strategy document generated</span>
                      </li>
                    )}
                    {monthlyThemes.length > 0 && (
                      <li className="flex items-start gap-2">
                        <LayoutGrid className="h-4 w-4 mt-0.5 shrink-0 text-primary" />
                        <span><strong>{monthlyThemes.length}</strong> monthly theme{monthlyThemes.length !== 1 ? "s" : ""} defined</span>
                      </li>
                    )}
                  </ul>
                </div>
              </>
            )}

            {report.error_message && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950">
                <p className="text-sm text-red-700 dark:text-red-400">
                  <AlertTriangle className="inline h-4 w-4 mr-1" />
                  {report.error_message}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ════════════════════════════════════════════════════════════
            RESEARCH REPORT SECTIONS
            ════════════════════════════════════════════════════════════ */}

        {/* ── Section 1: Market Gaps ──────────────────────────────── */}
        {isResearch && gapCount > 0 && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Target className="h-5 w-5 text-primary" />
                Market Gaps Analysis
              </CardTitle>
              <CardDescription>
                {gapCount} gap{gapCount !== 1 ? "s" : ""} identified across market segments
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {gaps.map((gap, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border p-4 space-y-3 hover:bg-muted/30 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-2 flex-wrap">
                        {gap.category && (
                          <Badge variant="outline" className="font-medium">
                            {gap.category}
                          </Badge>
                        )}
                        {gap.tier && (
                          <Badge variant="secondary" className="text-xs">
                            Tier: {gap.tier}
                          </Badge>
                        )}
                      </div>
                      {gap.priority && (
                        <Badge className={priorityColor(gap.priority)}>
                          {gap.priority}
                        </Badge>
                      )}
                    </div>

                    {gap.title && (
                      <h5 className="text-sm font-semibold">{gap.title}</h5>
                    )}

                    {gap.description && (
                      <p className="text-sm leading-relaxed">{gap.description}</p>
                    )}

                    {gap.opportunity && (
                      <div className="rounded-md bg-blue-50 p-3 dark:bg-blue-950">
                        <p className="text-xs font-semibold text-blue-700 dark:text-blue-400 mb-1">
                          <Lightbulb className="inline h-3.5 w-3.5 mr-1" />
                          Opportunity
                        </p>
                        <p className="text-sm text-blue-700 dark:text-blue-300">
                          {gap.opportunity}
                        </p>
                      </div>
                    )}

                    {gap.recommendation && (
                      <div className="rounded-md bg-emerald-50 p-3 dark:bg-emerald-950">
                        <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 mb-1">
                          Recommendation
                        </p>
                        <p className="text-sm text-emerald-700 dark:text-emerald-300">
                          {gap.recommendation}
                        </p>
                      </div>
                    )}

                    {gap.evidence && gap.evidence.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-semibold text-muted-foreground">
                          Evidence
                        </p>
                        <ul className="text-xs text-muted-foreground space-y-0.5">
                          {gap.evidence.map((e, i) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className="text-primary mt-0.5 shrink-0">&bull;</span>
                              {e}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {gap.confidence_score != null && (
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary transition-all"
                            style={{ width: `${Math.round(gap.confidence_score * 100)}%` }}
                          />
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {Math.round(gap.confidence_score * 100)}% confidence
                        </span>
                      </div>
                    )}

                    {/* Enriched gap fields */}
                    {(gap.estimated_impact || gap.implementation_effort || gap.recommended_timeline || gap.target_audience) && (
                      <div className="flex flex-wrap gap-2 pt-1">
                        {gap.estimated_impact && (
                          <Badge variant="outline" className="text-xs">Impact: {gap.estimated_impact}</Badge>
                        )}
                        {gap.implementation_effort && (
                          <Badge variant="outline" className="text-xs">Effort: {gap.implementation_effort}</Badge>
                        )}
                        {gap.recommended_timeline && (
                          <Badge variant="outline" className="text-xs">Timeline: {gap.recommended_timeline}</Badge>
                        )}
                        {gap.target_audience && (
                          <Badge variant="secondary" className="text-xs">Audience: {gap.target_audience}</Badge>
                        )}
                      </div>
                    )}

                    {gap.success_metrics && gap.success_metrics.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-semibold text-muted-foreground">Success Metrics</p>
                        <ul className="text-xs text-muted-foreground space-y-0.5">
                          {gap.success_metrics.map((m, i) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className="text-primary mt-0.5 shrink-0">&bull;</span>
                              {m}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Section 2: Audience Personas ────────────────────────── */}
        {isResearch && personaCount > 0 && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5 text-primary" />
                Audience Personas
              </CardTitle>
              <CardDescription>
                {personaCount} target persona{personaCount !== 1 ? "s" : ""} identified
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                {personas.map((persona, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border p-5 space-y-4"
                  >
                    {/* Persona header */}
                    <div className="flex items-center gap-3">
                      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                        <User className="h-6 w-6" />
                      </div>
                      <div>
                        <h4 className="font-semibold">
                          {persona.name || `Persona ${idx + 1}`}
                        </h4>
                        {persona.description && (
                          <p className="text-xs text-muted-foreground line-clamp-2">
                            {persona.description}
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Demographics */}
                    {persona.demographics && (
                      <div className="space-y-2">
                        <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Demographics
                        </h5>
                        <div className="grid grid-cols-2 gap-2 text-sm">
                          {persona.demographics.age_range && (
                            <div className="flex items-center gap-1.5">
                              <User className="h-3.5 w-3.5 text-muted-foreground" />
                              <span>{persona.demographics.age_range}</span>
                            </div>
                          )}
                          {persona.demographics.gender && (
                            <div className="flex items-center gap-1.5">
                              <Users className="h-3.5 w-3.5 text-muted-foreground" />
                              <span>{persona.demographics.gender}</span>
                            </div>
                          )}
                          {persona.demographics.location && (
                            <div className="flex items-center gap-1.5">
                              <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
                              <span>{persona.demographics.location}</span>
                            </div>
                          )}
                          {persona.demographics.income_level && (
                            <div className="flex items-center gap-1.5">
                              <DollarSign className="h-3.5 w-3.5 text-muted-foreground" />
                              <span>{persona.demographics.income_level}</span>
                            </div>
                          )}
                          {persona.demographics.occupation && (
                            <div className="flex items-center gap-1.5">
                              <Briefcase className="h-3.5 w-3.5 text-muted-foreground" />
                              <span>{persona.demographics.occupation}</span>
                            </div>
                          )}
                          {persona.demographics.education && (
                            <div className="flex items-center gap-1.5">
                              <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                              <span>{persona.demographics.education}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Psychographics */}
                    {persona.psychographics && (
                      <div className="space-y-2">
                        <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Psychographics
                        </h5>
                        <div className="space-y-1.5 text-sm">
                          {persona.psychographics.values &&
                            persona.psychographics.values && (
                              <div>
                                <span className="text-xs font-medium text-muted-foreground">
                                  Values:{" "}
                                </span>
                                <span>
                                  {Array.isArray(persona.psychographics.values)
                                    ? persona.psychographics.values.join(", ")
                                    : String(persona.psychographics.values)}
                                </span>
                              </div>
                            )}
                          {persona.psychographics.interests &&
                            persona.psychographics.interests.length > 0 && (
                              <div>
                                <span className="text-xs font-medium text-muted-foreground">
                                  Interests:{" "}
                                </span>
                                <span>
                                  {Array.isArray(persona.psychographics.interests)
                                    ? persona.psychographics.interests.join(", ")
                                    : String(persona.psychographics.interests)}
                                </span>
                              </div>
                            )}
                          {persona.psychographics.lifestyle && (
                            <div>
                              <span className="text-xs font-medium text-muted-foreground">
                                Lifestyle:{" "}
                              </span>
                              <span>{persona.psychographics.lifestyle}</span>
                            </div>
                          )}
                          {persona.psychographics.personality_traits &&
                            persona.psychographics.personality_traits.length > 0 && (
                              <div>
                                <span className="text-xs font-medium text-muted-foreground">
                                  Traits:{" "}
                                </span>
                                <span>
                                  {persona.psychographics.personality_traits.join(
                                    ", "
                                  )}
                                </span>
                              </div>
                            )}
                        </div>
                      </div>
                    )}

                    {/* Preferred platforms */}
                    {persona.preferred_platforms &&
                      persona.preferred_platforms.length > 0 && (
                        <div className="space-y-1.5">
                          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            Preferred Platforms
                          </h5>
                          <div className="flex flex-wrap gap-1.5">
                            {persona.preferred_platforms.map((p, i) => (
                              <Badge key={i} variant="secondary" className="text-xs">
                                {p}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}

                    {/* Pain points */}
                    {persona.pain_points && persona.pain_points.length > 0 && (
                      <div className="space-y-1.5">
                        <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                          <AlertTriangle className="h-3 w-3" /> Pain Points
                        </h5>
                        <ul className="text-sm space-y-1">
                          {persona.pain_points.map((pp, i) => (
                            <li key={i} className="flex items-start gap-1.5 text-muted-foreground">
                              <span className="text-red-500 mt-0.5 shrink-0">&bull;</span>
                              {pp}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Buying triggers */}
                    {persona.buying_triggers &&
                      persona.buying_triggers.length > 0 && (
                        <div className="space-y-1.5">
                          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                            <ShoppingCart className="h-3 w-3" /> Buying Triggers
                          </h5>
                          <ul className="text-sm space-y-1">
                            {persona.buying_triggers.map((bt, i) => (
                              <li key={i} className="flex items-start gap-1.5 text-muted-foreground">
                                <span className="text-emerald-500 mt-0.5 shrink-0">&bull;</span>
                                {bt}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                    {/* Content preferences */}
                    {persona.content_preferences && (
                      <div className="space-y-1.5">
                        <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                          <Heart className="h-3 w-3" /> Content Preferences
                        </h5>
                        {Array.isArray(persona.content_preferences) ? (
                          <div className="flex flex-wrap gap-1.5">
                            {persona.content_preferences.map((cp, i) => (
                              <Badge key={i} variant="outline" className="text-xs">
                                {cp}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <div className="space-y-1 text-sm">
                            {persona.content_preferences.formats && persona.content_preferences.formats.length > 0 && (
                              <div>
                                <span className="text-xs font-medium text-muted-foreground">Formats: </span>
                                <span>{persona.content_preferences.formats.join(", ")}</span>
                              </div>
                            )}
                            {persona.content_preferences.topics && persona.content_preferences.topics.length > 0 && (
                              <div>
                                <span className="text-xs font-medium text-muted-foreground">Topics: </span>
                                <span>{persona.content_preferences.topics.join(", ")}</span>
                              </div>
                            )}
                            {persona.content_preferences.tone && (
                              <div>
                                <span className="text-xs font-medium text-muted-foreground">Tone: </span>
                                <span>{persona.content_preferences.tone}</span>
                              </div>
                            )}
                            {persona.content_preferences.language_mix && (
                              <div>
                                <span className="text-xs font-medium text-muted-foreground">Language Mix: </span>
                                <span>
                                  {typeof persona.content_preferences.language_mix === "string"
                                    ? persona.content_preferences.language_mix
                                    : typeof persona.content_preferences.language_mix === "object"
                                    ? formatKeyValue(persona.content_preferences.language_mix as Record<string, string>)
                                    : null}
                                </span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Best engagement times */}
                    {persona.best_engagement_times && persona.best_engagement_times.length > 0 && (
                      <div className="space-y-1.5">
                        <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" /> Best Engagement Times
                        </h5>
                        <div className="flex flex-wrap gap-1.5">
                          {persona.best_engagement_times.map((t, i) => (
                            <Badge key={i} variant="secondary" className="text-xs">{t}</Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Content avoidance */}
                    {persona.content_avoidance && persona.content_avoidance.length > 0 && (
                      <div className="space-y-1.5">
                        <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                          <AlertTriangle className="h-3 w-3" /> Content to Avoid
                        </h5>
                        <ul className="text-sm space-y-1">
                          {persona.content_avoidance.map((ca, i) => (
                            <li key={i} className="flex items-start gap-1.5 text-muted-foreground">
                              <span className="text-orange-500 mt-0.5 shrink-0">&bull;</span>
                              {ca}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Section 3: Competitor Intelligence ──────────────────── */}
        {isResearch && <Card className="print-break">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-primary" />
              Competitor Intelligence
            </CardTitle>
            <CardDescription>
              {competitorCount > 0
                ? `${competitorCount} competitor${competitorCount !== 1 ? "s" : ""} analyzed`
                : "Competitor landscape overview"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {competitorCount === 0 && competitorUrls.length === 0 ? (
              <div className="text-center py-8 space-y-2">
                <Globe className="h-10 w-10 mx-auto text-muted-foreground/50" />
                <p className="text-sm text-muted-foreground">
                  No competitor data available. Add a website URL to the brand
                  profile to enable competitor discovery.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {competitorAnalysis.map((comp, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border p-4 space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <h4 className="font-semibold">
                          {comp.name || `Competitor ${idx + 1}`}
                        </h4>
                        {comp.threat_level && (
                          <Badge className={threatLevelColor(comp.threat_level)}>
                            {comp.threat_level} threat
                          </Badge>
                        )}
                      </div>
                      {comp.website_url && (
                        <a
                          href={comp.website_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-primary hover:underline flex items-center gap-1"
                        >
                          <ExternalLink className="h-3 w-3" />
                          Website
                        </a>
                      )}
                    </div>

                    {comp.positioning && (
                      <p className="text-sm">
                        <span className="text-xs font-semibold text-muted-foreground">Positioning: </span>
                        {comp.positioning}
                      </p>
                    )}

                    {comp.content_strategy && (
                      <p className="text-sm text-muted-foreground">
                        {comp.content_strategy}
                      </p>
                    )}

                    {comp.notes && (
                      <p className="text-sm text-muted-foreground italic">
                        {comp.notes}
                      </p>
                    )}

                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {comp.strengths && comp.strengths.length > 0 && (
                        <div className="rounded-md bg-green-50 p-3 dark:bg-green-950">
                          <p className="text-xs font-semibold text-green-700 dark:text-green-400 mb-1.5">
                            Strengths
                          </p>
                          <ul className="text-xs text-green-700 dark:text-green-300 space-y-0.5">
                            {comp.strengths.map((s, i) => (
                              <li key={i}>&bull; {s}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {comp.weaknesses && comp.weaknesses.length > 0 && (
                        <div className="rounded-md bg-red-50 p-3 dark:bg-red-950">
                          <p className="text-xs font-semibold text-red-700 dark:text-red-400 mb-1.5">
                            Weaknesses
                          </p>
                          <ul className="text-xs text-red-700 dark:text-red-300 space-y-0.5">
                            {comp.weaknesses.map((w, i) => (
                              <li key={i}>&bull; {w}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>

                    {comp.social_presence &&
                      Object.keys(comp.social_presence).length > 0 && (
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(comp.social_presence).map(
                            ([platform, handle]) => (
                              <Badge
                                key={platform}
                                variant="outline"
                                className="text-xs"
                              >
                                {platform}: {handle}
                              </Badge>
                            )
                          )}
                        </div>
                      )}
                  </div>
                ))}

                {competitorUrls.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-sm font-semibold">
                      Discovered Competitor URLs
                    </h4>
                    <div className="space-y-1">
                      {competitorUrls.map((url, idx) => (
                        <a
                          key={idx}
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-2 text-sm text-primary hover:underline"
                        >
                          <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                          {url}
                        </a>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>}

        {/* ── Section 4: Social Media Analysis ────────────────────── */}
        {isResearch && (socialAnalysis?.analysis ||
          socialAnalysis?.summary ||
          socialProfiles.length > 0) && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Share2 className="h-5 w-5 text-primary" />
                Social Media Analysis
              </CardTitle>
              <CardDescription>
                Social presence and engagement insights
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {(socialAnalysis?.analysis || socialAnalysis?.summary) && (
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <p className="text-sm leading-relaxed whitespace-pre-line">
                    {socialAnalysis.analysis || socialAnalysis.summary}
                  </p>
                </div>
              )}

              {socialAnalysis?.platforms &&
                socialAnalysis.platforms.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {socialAnalysis.platforms.map((p, i) => (
                      <Badge key={i} variant="secondary">
                        {p}
                      </Badge>
                    ))}
                  </div>
                )}

              {socialProfiles.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">Social Profiles</h4>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {socialProfiles.map((profile, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between rounded-md border p-3"
                      >
                        <div>
                          <p className="text-sm font-medium capitalize">
                            {profile.platform}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {profile.handle}
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          {profile.followers != null && (
                            <span className="text-xs text-muted-foreground">
                              {profile.followers.toLocaleString()} followers
                            </span>
                          )}
                          {profile.url && (
                            <a
                              href={profile.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary"
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ════════════════════════════════════════════════════════════
            STRATEGY REPORT SECTIONS
            ════════════════════════════════════════════════════════════ */}

        {/* ── Positioning ──────────────────────────────────────────── */}
        {isStrategy && positioning && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Compass className="h-5 w-5 text-primary" />
                Brand Positioning
              </CardTitle>
              <CardDescription>Strategic market positioning statement</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {typeof positioning === "string" ? (
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <p className="text-sm leading-relaxed whitespace-pre-line">{positioning}</p>
                </div>
              ) : typeof positioning === "object" && positioning !== null ? (
                <div className="space-y-4">
                  {/* Brand voice */}
                  {(positioning as Record<string, unknown>).brand_voice && (
                    <blockquote className="border-l-4 border-primary/30 pl-4 italic text-sm text-muted-foreground">
                      {String((positioning as Record<string, unknown>).brand_voice)}
                    </blockquote>
                  )}
                  {/* Value proposition */}
                  {(positioning as Record<string, unknown>).value_proposition && (
                    <div className="rounded-md bg-primary/5 border border-primary/20 p-3">
                      <p className="text-xs font-semibold text-muted-foreground mb-1">Value Proposition</p>
                      <p className="text-sm">{String((positioning as Record<string, unknown>).value_proposition)}</p>
                    </div>
                  )}
                  {/* Key messages */}
                  {Array.isArray((positioning as Record<string, unknown>).key_messages) && (
                    <div className="space-y-1">
                      <p className="text-xs font-semibold text-muted-foreground">Key Messages</p>
                      <ol className="list-decimal list-inside space-y-1 text-sm">
                        {((positioning as Record<string, unknown>).key_messages as string[]).map((msg, i) => (
                          <li key={i}>{msg}</li>
                        ))}
                      </ol>
                    </div>
                  )}
                  {/* Render remaining keys via SafeValue */}
                  {Object.entries(positioning as Record<string, unknown>)
                    .filter(([k]) => !["brand_voice", "value_proposition", "key_messages", "brand_archetype", "emotional_territory", "competitive_differentiation"].includes(k))
                    .map(([k, v]) => (
                      <div key={k}>
                        <p className="text-xs font-semibold text-muted-foreground capitalize mb-1">{k.replace(/_/g, " ")}</p>
                        <div className="text-sm"><SafeValue value={v} /></div>
                      </div>
                    ))}
                </div>
              ) : null}

              {(() => {
                const pos = typeof positioning === "object" && positioning !== null ? positioning as Record<string, unknown> : {};
                const archetype = output.brand_archetype || pos.brand_archetype;
                const territory = output.emotional_territory || pos.emotional_territory;
                return (archetype || territory) ? (
                  <div className="flex flex-wrap gap-3">
                    {archetype && (
                      <div className="rounded-md border p-3">
                        <p className="text-xs font-semibold text-muted-foreground mb-1">Brand Archetype</p>
                        <p className="text-sm font-medium">{String(archetype)}</p>
                      </div>
                    )}
                    {territory && (
                      <div className="rounded-md border p-3">
                        <p className="text-xs font-semibold text-muted-foreground mb-1">Emotional Territory</p>
                        <p className="text-sm font-medium">{String(territory)}</p>
                      </div>
                    )}
                  </div>
                ) : null;
              })()}

              {(() => {
                const pos = typeof positioning === "object" && positioning !== null ? positioning as Record<string, unknown> : {};
                const compDiff = output.competitive_differentiation || pos.competitive_differentiation;
                return Array.isArray(compDiff) && compDiff.length > 0 ? (
                  <div className="space-y-2">
                    <h4 className="text-sm font-semibold">Competitive Differentiation</h4>
                    <div className="rounded-md border overflow-hidden">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="bg-muted/50">
                            <th className="text-left p-2 font-semibold text-muted-foreground">Dimension</th>
                            <th className="text-left p-2 font-semibold text-muted-foreground">Brand</th>
                            <th className="text-left p-2 font-semibold text-muted-foreground">Competitors</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(compDiff as { dimension?: string; brand?: string; competitors?: string }[]).map((cd, i) => (
                            <tr key={i} className="border-t">
                              <td className="p-2 font-medium">{cd.dimension}</td>
                              <td className="p-2 text-muted-foreground">{cd.brand}</td>
                              <td className="p-2 text-muted-foreground">{cd.competitors}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : null;
              })()}
            </CardContent>
          </Card>
        )}

        {/* ── Content Pillars ─────────────────────────────────────── */}
        {isStrategy && contentPillars.length > 0 && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <LayoutGrid className="h-5 w-5 text-primary" />
                Content Pillars
              </CardTitle>
              <CardDescription>
                {contentPillars.length} pillar{contentPillars.length !== 1 ? "s" : ""} defining content strategy
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {contentPillars.map((pillar, idx) => (
                  <div key={idx} className="rounded-lg border p-4 space-y-3">
                    <h4 className="font-semibold flex items-center gap-2">
                      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary text-sm font-bold">
                        {idx + 1}
                      </div>
                      {typeof pillar === "string" ? pillar : (pillar.name || pillar.title || `Pillar ${idx + 1}`)}
                    </h4>
                    {typeof pillar === "object" && pillar.description && (
                      <p className="text-sm text-muted-foreground">{pillar.description}</p>
                    )}
                    {typeof pillar === "object" && pillar.topics && pillar.topics.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {pillar.topics.map((t: string, i: number) => (
                          <Badge key={i} variant="secondary" className="text-xs">{t}</Badge>
                        ))}
                      </div>
                    )}
                    {typeof pillar === "object" && pillar.content_types && pillar.content_types.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-semibold text-muted-foreground">Content Types</p>
                        <div className="flex flex-wrap gap-1.5">
                          {pillar.content_types.map((ct: string, i: number) => (
                            <Badge key={i} variant="outline" className="text-xs">{ct}</Badge>
                          ))}
                        </div>
                      </div>
                    )}
                    {typeof pillar === "object" && pillar.frequency && (
                      <p className="text-xs text-muted-foreground flex items-center gap-1">
                        <CalendarDays className="h-3 w-3" /> {pillar.frequency}
                      </p>
                    )}
                    {typeof pillar === "object" && pillar.pillar_rationale && (
                      <p className="text-xs text-muted-foreground italic">{pillar.pillar_rationale}</p>
                    )}
                    {typeof pillar === "object" && (pillar.audience_alignment || pillar.seasonal_emphasis || pillar.platform_fit || pillar.visual_style) && (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {pillar.audience_alignment && (
                          <Badge variant="outline" className="text-[10px]">Audience: {pillar.audience_alignment}</Badge>
                        )}
                        {pillar.seasonal_emphasis && (
                          <Badge variant="outline" className="text-[10px]">Season: {pillar.seasonal_emphasis}</Badge>
                        )}
                        {pillar.platform_fit && (
                          <Badge variant="outline" className="text-[10px]">Platform: {pillar.platform_fit}</Badge>
                        )}
                        {pillar.visual_style && (
                          <Badge variant="outline" className="text-[10px]">Visual: {pillar.visual_style}</Badge>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Target Audiences ────────────────────────────────────── */}
        {isStrategy && targetAudiences.length > 0 && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5 text-primary" />
                Target Audiences
              </CardTitle>
              <CardDescription>
                {targetAudiences.length} audience segment{targetAudiences.length !== 1 ? "s" : ""} identified
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {targetAudiences.map((audience, idx) => (
                  <div key={idx} className="rounded-lg border p-4 space-y-3">
                    <h4 className="font-semibold">
                      {typeof audience === "string" ? audience : (audience.name || audience.segment || `Audience ${idx + 1}`)}
                    </h4>
                    {typeof audience === "object" && audience.description && (
                      <p className="text-sm text-muted-foreground">{audience.description}</p>
                    )}
                    {typeof audience === "object" && audience.platforms && audience.platforms.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {audience.platforms.map((p: string, i: number) => (
                          <Badge key={i} variant="secondary" className="text-xs">{p}</Badge>
                        ))}
                      </div>
                    )}
                    {typeof audience === "object" && audience.content_preferences && audience.content_preferences.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-semibold text-muted-foreground">Content Preferences</p>
                        <ul className="text-xs text-muted-foreground space-y-0.5">
                          {audience.content_preferences.map((cp: string, i: number) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className="text-primary mt-0.5">&bull;</span> {cp}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Posting Cadence ─────────────────────────────────────── */}
        {isStrategy && postingCadence && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CalendarDays className="h-5 w-5 text-primary" />
                Posting Cadence
              </CardTitle>
              <CardDescription>Recommended posting frequency and schedule</CardDescription>
            </CardHeader>
            <CardContent>
              {typeof postingCadence === "string" ? (
                <p className="text-sm leading-relaxed whitespace-pre-line">{postingCadence}</p>
              ) : (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {Object.entries(postingCadence).map(([platform, schedule]) => (
                    <div key={platform} className="rounded-md border p-3">
                      <p className="text-sm font-medium capitalize">{platform}</p>
                      <p className="text-xs text-muted-foreground">
                        {typeof schedule === "string" ? schedule : <SafeValue value={schedule} />}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── Monthly Themes (Strategy) ───────────────────────────── */}
        {isStrategy && monthlyThemes.length > 0 && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <LayoutGrid className="h-5 w-5 text-primary" />
                Monthly Themes
              </CardTitle>
              <CardDescription>{monthlyThemes.length} month{monthlyThemes.length !== 1 ? "s" : ""} themed</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {monthlyThemes.map((theme, idx) => (
                  <div key={idx} className="rounded-lg border p-4 space-y-2">
                    <div className="flex items-center justify-between">
                      <h4 className="text-sm font-semibold">
                        {typeof theme === "string" ? theme : (theme.month || `Month ${idx + 1}`)}
                      </h4>
                      {typeof theme === "object" && (theme.theme || theme.name) && (
                        <Badge variant="outline" className="text-xs">{theme.theme || theme.name}</Badge>
                      )}
                    </div>
                    {typeof theme === "object" && theme.description && (
                      <p className="text-xs text-muted-foreground">{theme.description}</p>
                    )}
                    {typeof theme === "object" && theme.focus_areas && theme.focus_areas.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {theme.focus_areas.map((fa: string, i: number) => (
                          <Badge key={i} variant="secondary" className="text-[10px]">{fa}</Badge>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ════════════════════════════════════════════════════════════
            PLANNING REPORT SECTIONS
            ════════════════════════════════════════════════════════════ */}

        {/* ── Campaigns ───────────────────────────────────────────── */}
        {isPlanning && campaigns.length > 0 && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Megaphone className="h-5 w-5 text-primary" />
                Campaigns
              </CardTitle>
              <CardDescription>
                {campaigns.length} campaign{campaigns.length !== 1 ? "s" : ""} planned
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {campaigns.map((campaign, idx) => (
                  <div key={idx} className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <h4 className="font-semibold">
                        {typeof campaign === "string" ? campaign : (campaign.name || campaign.title || `Campaign ${idx + 1}`)}
                      </h4>
                      {typeof campaign === "object" && campaign.status && (
                        <Badge variant="outline">{campaign.status}</Badge>
                      )}
                    </div>
                    {typeof campaign === "object" && campaign.description && (
                      <p className="text-sm text-muted-foreground">{campaign.description}</p>
                    )}
                    {typeof campaign === "object" && (campaign.start_date || campaign.end_date) && (
                      <p className="text-xs text-muted-foreground flex items-center gap-1">
                        <CalendarDays className="h-3 w-3" />
                        {campaign.start_date && <span>Start: {campaign.start_date}</span>}
                        {campaign.start_date && campaign.end_date && <span className="mx-1">-</span>}
                        {campaign.end_date && <span>End: {campaign.end_date}</span>}
                      </p>
                    )}
                    {typeof campaign === "object" && campaign.channels && campaign.channels.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {campaign.channels.map((ch: string, i: number) => (
                          <Badge key={i} variant="secondary" className="text-xs">{ch}</Badge>
                        ))}
                      </div>
                    )}
                    {typeof campaign === "object" && campaign.objectives && campaign.objectives.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-xs font-semibold text-muted-foreground">Objectives</p>
                        <ul className="text-xs text-muted-foreground space-y-0.5">
                          {campaign.objectives.map((obj: string, i: number) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className="text-primary mt-0.5">&bull;</span> {obj}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Calendar Summary ────────────────────────────────────── */}
        {isPlanning && calendarSummary && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CalendarDays className="h-5 w-5 text-primary" />
                Calendar Summary
              </CardTitle>
              <CardDescription>Overview of planned content schedule</CardDescription>
            </CardHeader>
            <CardContent>
              {typeof calendarSummary === "string" ? (
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <ReactMarkdown>{calendarSummary}</ReactMarkdown>
                </div>
              ) : (
                <div className="text-sm">
                  <SafeValue value={calendarSummary} />
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ════════════════════════════════════════════════════════════
            CONTENT CALENDAR STRATEGY SECTIONS
            ════════════════════════════════════════════════════════════ */}

        {/* ── Strategy Document (Markdown) ────────────────────────── */}
        {isContentCalendar && strategyDocument && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BookOpen className="h-5 w-5 text-primary" />
                Strategy Document
              </CardTitle>
              <CardDescription>Full year-long content calendar strategy</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:text-foreground prose-p:text-muted-foreground prose-strong:text-foreground prose-li:text-muted-foreground">
                {typeof strategyDocument === "string"
                  ? <ReactMarkdown>{strategyDocument}</ReactMarkdown>
                  : <SafeValue value={strategyDocument} />}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Monthly Themes (Content Calendar) ───────────────────── */}
        {isContentCalendar && monthlyThemes.length > 0 && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <LayoutGrid className="h-5 w-5 text-primary" />
                Monthly Themes
              </CardTitle>
              <CardDescription>{monthlyThemes.length} month{monthlyThemes.length !== 1 ? "s" : ""} planned</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {monthlyThemes.map((theme, idx) => (
                  <div key={idx} className="rounded-lg border p-4 space-y-2">
                    <div className="flex items-center justify-between">
                      <h4 className="text-sm font-semibold">
                        {typeof theme === "string" ? theme : (theme.month || `Month ${idx + 1}`)}
                      </h4>
                      {typeof theme === "object" && (theme.theme || theme.name) && (
                        <Badge variant="outline" className="text-xs">{theme.theme || theme.name}</Badge>
                      )}
                    </div>
                    {typeof theme === "object" && theme.description && (
                      <p className="text-xs text-muted-foreground">{theme.description}</p>
                    )}
                    {typeof theme === "object" && theme.focus_areas && theme.focus_areas.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {theme.focus_areas.map((fa: string, i: number) => (
                          <Badge key={i} variant="secondary" className="text-[10px]">{fa}</Badge>
                        ))}
                      </div>
                    )}
                    {typeof theme === "object" && theme.campaigns && theme.campaigns.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {theme.campaigns.map((c: string, i: number) => (
                          <Badge key={i} variant="outline" className="text-[10px]">{c}</Badge>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ════════════════════════════════════════════════════════════
            GENERIC FALLBACK — raw output for unknown types
            ════════════════════════════════════════════════════════════ */}
        {!isResearch && !isStrategy && !isPlanning && !isContentCalendar && output && Object.keys(output).length > 0 && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-primary" />
                Report Output
              </CardTitle>
              <CardDescription>Raw output data from agent run</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-sm space-y-3">
                <SafeValue value={output} />
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Section 5: Errors & Recommendations ─────────────────── */}
        {(errors.length > 0 || recommendations.length > 0) && (
          <Card className="print-break">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Lightbulb className="h-5 w-5 text-primary" />
                {errors.length > 0 && recommendations.length > 0
                  ? "Issues & Recommendations"
                  : errors.length > 0
                  ? "Issues Encountered"
                  : "Recommendations"}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {errors.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold text-red-600 dark:text-red-400 flex items-center gap-1.5">
                    <AlertTriangle className="h-4 w-4" /> Errors
                  </h4>
                  <ul className="space-y-1.5">
                    {errors.map((err, i) => (
                      <li
                        key={i}
                        className="flex items-start gap-2 text-sm rounded-md border border-red-200 bg-red-50 p-2.5 dark:border-red-900 dark:bg-red-950"
                      >
                        <span className="text-red-500 mt-0.5 shrink-0">&bull;</span>
                        <span className="text-red-700 dark:text-red-300">{err}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {recommendations.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">
                    Recommendations
                  </h4>
                  <ul className="space-y-1.5">
                    {recommendations.map((rec, i) => (
                      <li
                        key={i}
                        className="flex items-start gap-2 text-sm rounded-md border border-emerald-200 bg-emerald-50 p-2.5 dark:border-emerald-900 dark:bg-emerald-950"
                      >
                        <span className="text-emerald-500 mt-0.5 shrink-0">&bull;</span>
                        <span className="text-emerald-700 dark:text-emerald-300">
                          {rec}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── Footer ──────────────────────────────────────────────── */}
        <div className="text-center text-xs text-muted-foreground py-4 border-t">
          <p>
            Report generated by MARKAI Intelligence Engine
            {report.completed_at && <> on {formatDate(report.completed_at)}</>}
          </p>
          <p className="mt-1">Report ID: {report.id}</p>
        </div>
      </div>
    </>
  );
}
