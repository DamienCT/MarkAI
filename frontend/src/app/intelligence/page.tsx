"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";
import {
  FileText,
  Search,
  Lightbulb,
  CalendarDays,
  BookOpen,
  ArrowRight,
  Clock,
  CheckCircle2,
  Loader2,
  AlertCircle,
  Target,
  Users,
  TrendingUp,
  Compass,
  LayoutGrid,
  Megaphone,
} from "lucide-react";
import { formatKeyValue } from "@/components/ui/safe-render";

// ── Types ────────────────────────────────────────────────────────────

interface AgentReport {
  id: string;
  brand_id: string | null;
  report_type: string;
  status: string;
  title: string;
  summary: string;
  insights: string[];
  output_payload: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
}

interface TrendData {
  id: string;
  topic: string;
  platform: string;
  relevance_score: number;
  description: string;
  discovered_at: string;
}

interface ReportCardConfig {
  agentType: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  accentColor: string;
  renderPreview: (report: AgentReport) => React.ReactNode;
}

// ── Status badge helper ──────────────────────────────────────────────

function StatusBadge({ status }: { status: string | undefined }) {
  if (!status) {
    return (
      <Badge variant="outline" className="text-xs gap-1 text-muted-foreground border-muted">
        <AlertCircle className="h-3 w-3" />
        Not Available
      </Badge>
    );
  }
  switch (status) {
    case "completed":
      return (
        <Badge className="text-xs gap-1 bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300 hover:bg-green-100">
          <CheckCircle2 className="h-3 w-3" />
          Completed
        </Badge>
      );
    case "running":
    case "pending":
      return (
        <Badge className="text-xs gap-1 bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300 hover:bg-blue-100">
          <Loader2 className="h-3 w-3 animate-spin" />
          {status === "running" ? "Running" : "Pending"}
        </Badge>
      );
    case "failed":
      return (
        <Badge className="text-xs gap-1 bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300 hover:bg-red-100">
          <AlertCircle className="h-3 w-3" />
          Failed
        </Badge>
      );
    default:
      return (
        <Badge variant="outline" className="text-xs gap-1">
          {status}
        </Badge>
      );
  }
}

// ── Preview renderers per report type ────────────────────────────────

function ResearchPreview({ report }: { report: AgentReport }) {
  const output = report.output_payload || {};
  const gaps = (output.gaps as Array<Record<string, unknown>>) || [];
  const personas = (output.personas as Array<Record<string, unknown>>) || [];
  const competitors = (output.competitor_analysis as Array<Record<string, unknown>>) || [];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-md border p-2.5 text-center">
          <p className="text-lg font-bold text-primary">{gaps.length}</p>
          <p className="text-[10px] text-muted-foreground">Market Gaps</p>
        </div>
        <div className="rounded-md border p-2.5 text-center">
          <p className="text-lg font-bold text-primary">{personas.length}</p>
          <p className="text-[10px] text-muted-foreground">Personas</p>
        </div>
        <div className="rounded-md border p-2.5 text-center">
          <p className="text-lg font-bold text-primary">{competitors.length}</p>
          <p className="text-[10px] text-muted-foreground">Competitors</p>
        </div>
      </div>
      {gaps.length > 0 && (
        <ul className="text-xs text-muted-foreground space-y-1">
          {gaps.slice(0, 3).map((gap, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <Target className="h-3 w-3 mt-0.5 shrink-0 text-primary" />
              <span className="line-clamp-1">{(gap.description as string) || (gap.category as string) || `Gap ${i + 1}`}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StrategyPreview({ report }: { report: AgentReport }) {
  const output = report.output_payload || {};
  const pillars = (output.content_pillars as Array<Record<string, unknown> | string>) || [];
  const audiences = (output.target_audiences as Array<Record<string, unknown> | string>) || [];
  const positioning = output.positioning as string | undefined;
  const cadence = output.posting_cadence as Record<string, unknown> | string | undefined;
  const themes = (output.monthly_themes as Array<Record<string, unknown> | string>) || [];

  return (
    <div className="space-y-3">
      {positioning && (
        <div className="rounded-md bg-blue-50 dark:bg-blue-950 p-2.5">
          <p className="text-[10px] font-semibold text-blue-700 dark:text-blue-400 mb-0.5 flex items-center gap-1">
            <Compass className="h-3 w-3" /> Positioning
          </p>
          <p className="text-xs text-blue-700 dark:text-blue-300 line-clamp-2">
            {typeof positioning === "string" ? positioning : typeof positioning === "object" && positioning !== null ? formatKeyValue(positioning as Record<string, string>) : String(positioning)}
          </p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        {pillars.length > 0 && (
          <div className="rounded-md border p-2.5 text-center">
            <p className="text-lg font-bold text-primary">{pillars.length}</p>
            <p className="text-[10px] text-muted-foreground">Content Pillars</p>
          </div>
        )}
        {audiences.length > 0 && (
          <div className="rounded-md border p-2.5 text-center">
            <p className="text-lg font-bold text-primary">{audiences.length}</p>
            <p className="text-[10px] text-muted-foreground">Target Audiences</p>
          </div>
        )}
      </div>
      {cadence && (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <CalendarDays className="h-3 w-3 shrink-0 text-primary" />
          Posting cadence: {typeof cadence === "string" ? cadence : "Defined"}
        </p>
      )}
      {themes.length > 0 && (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <LayoutGrid className="h-3 w-3 shrink-0 text-primary" />
          {themes.length} monthly theme(s) mapped
        </p>
      )}
    </div>
  );
}

function PlanningPreview({ report }: { report: AgentReport }) {
  const output = report.output_payload || {};
  const campaigns = (output.campaigns as Array<Record<string, unknown>>) || [];
  const calendarSummary = (output.calendar_summary || output.calendar) as string | Record<string, unknown> | undefined;

  return (
    <div className="space-y-3">
      {campaigns.length > 0 && (
        <>
          <div className="rounded-md border p-2.5 text-center">
            <p className="text-lg font-bold text-primary">{campaigns.length}</p>
            <p className="text-[10px] text-muted-foreground">Campaigns Planned</p>
          </div>
          <ul className="text-xs text-muted-foreground space-y-1">
            {campaigns.slice(0, 4).map((c, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <Megaphone className="h-3 w-3 mt-0.5 shrink-0 text-primary" />
                <span className="line-clamp-1">
                  {(c.name as string) || (c.title as string) || `Campaign ${i + 1}`}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {calendarSummary && (
        <div className="rounded-md bg-amber-50 dark:bg-amber-950 p-2.5">
          <p className="text-[10px] font-semibold text-amber-700 dark:text-amber-400 mb-0.5">Calendar Summary</p>
          <p className="text-xs text-amber-700 dark:text-amber-300 line-clamp-3">
            {typeof calendarSummary === "string"
              ? calendarSummary.slice(0, 200)
              : "Calendar data available"}
          </p>
        </div>
      )}
      {campaigns.length === 0 && !calendarSummary && (
        <p className="text-xs text-muted-foreground text-center py-2">Plan data available - view full report for details</p>
      )}
    </div>
  );
}

function ContentCalendarStrategyPreview({ report }: { report: AgentReport }) {
  const output = report.output_payload || {};
  const doc = (output.strategy_document || output.markdown || output.content) as string | undefined;
  const themes = (output.monthly_themes as Array<Record<string, unknown> | string>) || [];

  return (
    <div className="space-y-3">
      {themes.length > 0 && (
        <div className="rounded-md border p-2.5 text-center">
          <p className="text-lg font-bold text-primary">{themes.length}</p>
          <p className="text-[10px] text-muted-foreground">Monthly Themes</p>
        </div>
      )}
      {doc && (
        <div className="rounded-md bg-violet-50 dark:bg-violet-950 p-2.5">
          <p className="text-[10px] font-semibold text-violet-700 dark:text-violet-400 mb-0.5">Strategy Document</p>
          <p className="text-xs text-violet-700 dark:text-violet-300 line-clamp-4">
            {doc.slice(0, 300).replace(/[#*_]/g, "")}...
          </p>
        </div>
      )}
      {!doc && themes.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-2">Strategy document available - view full report</p>
      )}
    </div>
  );
}

// ── Report card configs ──────────────────────────────────────────────

const REPORT_CARDS: ReportCardConfig[] = [
  {
    agentType: "research",
    title: "Research Report",
    description: "Market gaps, audience personas, competitor analysis",
    icon: <Search className="h-5 w-5" />,
    accentColor: "text-emerald-600 dark:text-emerald-400",
    renderPreview: (report) => <ResearchPreview report={report} />,
  },
  {
    agentType: "strategy",
    title: "Marketing Strategy",
    description: "Positioning, content pillars, target audiences, cadence",
    icon: <Lightbulb className="h-5 w-5" />,
    accentColor: "text-blue-600 dark:text-blue-400",
    renderPreview: (report) => <StrategyPreview report={report} />,
  },
  {
    agentType: "planning",
    title: "Marketing Plan",
    description: "Campaigns, calendar summary, execution timeline",
    icon: <CalendarDays className="h-5 w-5" />,
    accentColor: "text-amber-600 dark:text-amber-400",
    renderPreview: (report) => <PlanningPreview report={report} />,
  },
  {
    agentType: "content_calendar",
    title: "Content Calendar Strategy",
    description: "Year-long strategy document with monthly themes",
    icon: <BookOpen className="h-5 w-5" />,
    accentColor: "text-violet-600 dark:text-violet-400",
    renderPreview: (report) => <ContentCalendarStrategyPreview report={report} />,
  },
];

// ── Main page ────────────────────────────────────────────────────────

interface BrandOption {
  id: string;
  name: string;
}

export default function IntelligencePage() {
  const router = useRouter();
  const [reports, setReports] = useState<AgentReport[]>([]);
  const [trends, setTrends] = useState<TrendData[]>([]);
  const [brands, setBrands] = useState<BrandOption[]>([]);
  const [selectedBrand, setSelectedBrand] = useState<string>("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<BrandOption[]>("/api/v1/brands").then(setBrands).catch(() => {});
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchData() {
      setLoading(true);
      try {
        const params: Record<string, string | number> = { limit: 50 };
        if (selectedBrand !== "all") params.brand_id = selectedBrand;
        const [reportsData, trendsData] = await Promise.allSettled([
          api.get<AgentReport[]>("/api/v1/intelligence/reports", params, { signal }),
          api.get<TrendData[]>("/api/v1/intelligence/trends", { limit: 20 }, { signal }),
        ]);
        if (reportsData.status === "fulfilled") setReports(reportsData.value);
        if (trendsData.status === "fulfilled") setTrends(trendsData.value);
      } catch {
        toast.error("Failed to load intelligence data");
      } finally {
        setLoading(false);
      }
    }
    fetchData();

    return () => controller.abort();
  }, [selectedBrand]);

  // Find the latest report for each agent type
  function getLatestByType(agentType: string): AgentReport | undefined {
    return reports.find((r) => r.report_type === agentType);
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Intelligence</h1>
        <p className="text-muted-foreground">Research, trends, and competitor insights</p>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold">Intelligence</h1>
          <p className="text-muted-foreground">Research, strategy, planning, and content calendar insights</p>
        </div>
        {brands.length > 0 && (
          <Select value={selectedBrand} onValueChange={setSelectedBrand}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="All Brands" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Brands</SelectItem>
              {brands.map(b => (
                <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* ── 4 Report Cards ──────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {REPORT_CARDS.map((config) => {
          const latest = getLatestByType(config.agentType);

          return (
            <Card
              key={config.agentType}
              className={`relative overflow-hidden transition-all ${
                latest ? "hover:border-primary/40 hover:shadow-md cursor-pointer" : "opacity-75"
              }`}
              onClick={() => latest && router.push(`/intelligence/report/${latest.id}`)}
            >
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`${config.accentColor}`}>
                      {config.icon}
                    </div>
                    <div>
                      <CardTitle className="text-base">{config.title}</CardTitle>
                      <CardDescription className="text-xs mt-0.5">
                        {config.description}
                      </CardDescription>
                    </div>
                  </div>
                  <StatusBadge status={latest?.status} />
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {latest ? (
                  <>
                    {/* Summary line */}
                    <p className="text-sm text-muted-foreground">{latest.summary}</p>

                    {/* Type-specific preview */}
                    {config.renderPreview(latest)}

                    {/* Footer: timestamp + arrow hint */}
                    <div className="flex items-center justify-between pt-2 border-t">
                      <span className="text-xs text-muted-foreground flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatRelativeTime(latest.completed_at || latest.created_at)}
                      </span>
                      <ArrowRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </>
                ) : (
                  <div className="text-center py-6 space-y-2">
                    <FileText className="h-8 w-8 mx-auto text-muted-foreground/40" />
                    <p className="text-sm text-muted-foreground">
                      No {config.title.toLowerCase()} generated yet
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Run the {config.agentType.replace(/_/g, " ")} agent to generate this report
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* ── Trends Section ────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-primary" />
            Trending Topics
          </CardTitle>
          <CardDescription>Current trends and emerging topics</CardDescription>
        </CardHeader>
        <CardContent>
          {trends.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No trending topics detected</p>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {trends.map((trend, idx) => (
                <div key={trend.id || idx} className="flex items-center justify-between rounded-md border p-3">
                  <div>
                    <p className="text-sm font-medium">{trend.topic}</p>
                    <p className="text-xs text-muted-foreground capitalize">{trend.platform}</p>
                  </div>
                  <div className="text-right">
                    <Badge variant="outline">
                      {Math.round(trend.relevance_score * 100)}% relevant
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
