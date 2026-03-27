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
  gaps?: MarketGap[];
  personas?: Persona[];
  competitor_analysis?: CompetitorAnalysis[];
  competitor_urls?: string[];
  social_analysis?: SocialAnalysis;
  social_profiles?: SocialProfile[];
  errors?: string[];
  recommendations?: string[];
  [key: string]: unknown;
}

interface MarketGap {
  category?: string;
  priority?: string;
  description?: string;
  opportunity?: string;
  recommendation?: string;
  tier?: string;
  confidence_score?: number;
  evidence?: string[];
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
  content_preferences?: string[];
  description?: string;
}

interface CompetitorAnalysis {
  name?: string;
  website_url?: string;
  strengths?: string[];
  weaknesses?: string[];
  social_presence?: Record<string, string>;
  content_strategy?: string;
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
  const gaps = output.gaps || [];
  const personas = output.personas || [];
  const competitorAnalysis = output.competitor_analysis || [];
  const competitorUrls = output.competitor_urls || [];
  const socialAnalysis = output.social_analysis;
  const socialProfiles = output.social_profiles || [];
  const errors = output.errors || [];
  const recommendations = output.recommendations || [];

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
            {/* Stats grid */}
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

            {/* Key findings */}
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

        {/* ── Section 1: Market Gaps ──────────────────────────────── */}
        {gapCount > 0 && (
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
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Section 2: Audience Personas ────────────────────────── */}
        {personaCount > 0 && (
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
                    {persona.content_preferences &&
                      persona.content_preferences.length > 0 && (
                        <div className="space-y-1.5">
                          <h5 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                            <Heart className="h-3 w-3" /> Content Preferences
                          </h5>
                          <div className="flex flex-wrap gap-1.5">
                            {persona.content_preferences.map((cp, i) => (
                              <Badge key={i} variant="outline" className="text-xs">
                                {cp}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Section 3: Competitor Intelligence ──────────────────── */}
        <Card className="print-break">
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
                      <h4 className="font-semibold">
                        {comp.name || `Competitor ${idx + 1}`}
                      </h4>
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
        </Card>

        {/* ── Section 4: Social Media Analysis ────────────────────── */}
        {(socialAnalysis?.analysis ||
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
