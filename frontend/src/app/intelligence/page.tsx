"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { getStoredBrandValue } from "@/lib/brand-selection";
import { useRequireRole } from "@/lib/hooks";
import { formatRelativeTime } from "@/lib/utils";
import {
  FileText,
  Search,
  Lightbulb,
  CalendarDays,
  BookOpen,
  ArrowRight,
  ArrowDown,
  ArrowUp,
  Clock,
  CheckCircle2,
  CheckSquare,
  Loader2,
  AlertCircle,
  Square,
  Target,
  Trash2,
  TrendingUp,
  Compass,
  LayoutGrid,
  Megaphone,
  MapPin,
  X,
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
  source_url: string | null;
  relevance_score: number;
  relevance_reason: string | null;
  llm_angle: string | null;
  velocity: "rising" | "stable" | "falling";
  raw_metric: string | null;
  geo: string | null;
  discovered_at: string;
  brand_id: string;
  brand_name: string;
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
  useRequireRole("viewer"); // redirects unauthorized users as a side effect
  const router = useRouter();
  const [reports, setReports] = useState<AgentReport[]>([]);
  const [trends, setTrends] = useState<TrendData[]>([]);
  const [brands, setBrands] = useState<BrandOption[]>([]);
  const [selectedBrand, setSelectedBrand] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [refreshingTrends, setRefreshingTrends] = useState(false);
  const [trendsSortDir, setTrendsSortDir] = useState<"desc" | "asc">("desc");
  const [localTrendOnly, setLocalTrendOnly] = useState(false);
  const [trendsSelectMode, setTrendsSelectMode] = useState(false);
  const [selectedTrendIds, setSelectedTrendIds] = useState<Set<string>>(new Set());
  const [deletingTrends, setDeletingTrends] = useState(false);

  useEffect(() => {
    setSelectedBrand(getStoredBrandValue());
    api.get<BrandOption[]>("/api/v1/brands").then(setBrands).catch(() => {});

    const handler = (e: Event) => {
      const brandId = (e as CustomEvent).detail?.brandId;
      setSelectedBrand(brandId || "all");
    };
    window.addEventListener("brand-changed", handler);
    return () => window.removeEventListener("brand-changed", handler);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchData() {
      setLoading(true);
      try {
        const reportsParams: Record<string, string | number> = { limit: 50 };
        if (selectedBrand !== "all") reportsParams.brand_id = selectedBrand;
        const trendsParams: Record<string, string | number> = { limit: 20 };
        if (selectedBrand !== "all") trendsParams.brand_id = selectedBrand;
        const [reportsData, trendsData] = await Promise.allSettled([
          api.get<AgentReport[]>("/api/v1/intelligence/reports", reportsParams, { signal }),
          api.get<TrendData[]>("/api/v1/intelligence/trends", trendsParams, { signal }),
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

  // Manual refresh of trends — kicks the cron job immediately and polls
  // for fresh rows. The backend job runs in the background and typically
  // finishes in 30-90s (one pytrends call + one LLM call per brand).
  const handleRefreshTrends = async () => {
    if (refreshingTrends) return;
    setRefreshingTrends(true);
    try {
      await api.post("/api/v1/intelligence/trends/refresh");
      toast.success("Trends refresh started — results will appear in ~1 minute.");
      // Poll every 15s for up to 2 min, replace `trends` when new data arrives
      let elapsed = 0;
      const tick = async () => {
        try {
          const params: Record<string, string | number> = { limit: 20 };
          if (selectedBrand !== "all") params.brand_id = selectedBrand;
          const fresh = await api.get<TrendData[]>("/api/v1/intelligence/trends", params);
          if (Array.isArray(fresh) && fresh.length > 0) {
            setTrends(fresh);
          }
        } catch {
          // poll failure ignored
        }
        elapsed += 15;
        if (elapsed >= 120) {
          setRefreshingTrends(false);
        } else {
          setTimeout(tick, 15000);
        }
      };
      setTimeout(tick, 15000);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail;
      toast.error(detail || "Could not start the trends refresh");
      setRefreshingTrends(false);
    }
  };

  // Find the latest report for each agent type
  function getLatestByType(agentType: string): AgentReport | undefined {
    return reports.find((r) => r.report_type === agentType);
  }

  const toggleTrendSelect = (id: string) => {
    setSelectedTrendIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const exitTrendSelectMode = () => {
    setTrendsSelectMode(false);
    setSelectedTrendIds(new Set());
  };

  const handleBulkDeleteTrends = async () => {
    if (selectedTrendIds.size === 0) return;
    const n = selectedTrendIds.size;
    if (!window.confirm(`Delete ${n} trend${n !== 1 ? "s" : ""}? This cannot be undone.`)) {
      return;
    }
    setDeletingTrends(true);
    const ids = Array.from(selectedTrendIds);
    try {
      const results = await Promise.allSettled(
        ids.map((id) => api.delete<unknown>(`/api/v1/intelligence/trends/${id}`))
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const failed = results.length - ok;
      if (ok) {
        setTrends((cur) => cur.filter((t) => !selectedTrendIds.has(t.id)));
        toast.success(`Deleted ${ok} trend${ok !== 1 ? "s" : ""}`);
      }
      if (failed) {
        toast.error(`Failed to delete ${failed} trend${failed !== 1 ? "s" : ""}`);
      }
      exitTrendSelectMode();
    } finally {
      setDeletingTrends(false);
    }
  };

  // Trends sorted by discovery date; toggle flips the order.
  const sortedTrends = useMemo(() => {
    const copy = [...trends];
    copy.sort((a, b) => {
      const diff =
        new Date(b.discovered_at).getTime() - new Date(a.discovered_at).getTime();
      return trendsSortDir === "desc" ? diff : -diff;
    });
    return copy;
  }, [trends, trendsSortDir]);

  // "Local Trend" filter → Mauritius (geo === "MU") only.
  const displayedTrends = useMemo(
    () =>
      localTrendOnly
        ? sortedTrends.filter((t) => (t.geo || "").toUpperCase() === "MU")
        : sortedTrends,
    [sortedTrends, localTrendOnly]
  );
  const localTrendCount = useMemo(
    () => sortedTrends.filter((t) => (t.geo || "").toUpperCase() === "MU").length,
    [sortedTrends]
  );

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
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <CardTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5 text-primary" />
                Trending Topics
              </CardTitle>
              <CardDescription>
                Worldwide Trends, scored and ranked by AI for each brand. Click a card to generate a post.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {trendsSelectMode ? (
                <>
                  <span className="text-sm text-muted-foreground">
                    {selectedTrendIds.size} selected
                  </span>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={selectedTrendIds.size === 0 || deletingTrends}
                    onClick={handleBulkDeleteTrends}
                  >
                    {deletingTrends ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    Delete
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={exitTrendSelectMode}
                    disabled={deletingTrends}
                  >
                    <X className="mr-1.5 h-3.5 w-3.5" />
                    Cancel
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    variant={localTrendOnly ? "default" : "outline"}
                    size="sm"
                    onClick={() => setLocalTrendOnly((v) => !v)}
                    title={
                      localTrendOnly
                        ? "Mauritius filter active — click to clear"
                        : "Show only local (Mauritius) trends"
                    }
                  >
                    {localTrendOnly ? (
                      <X className="mr-1.5 h-3.5 w-3.5" />
                    ) : (
                      <MapPin className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    Local Trend
                    {!localTrendOnly && localTrendCount > 0 ? ` (${localTrendCount})` : ""}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setTrendsSelectMode(true)}
                    disabled={displayedTrends.length === 0}
                  >
                    <CheckSquare className="mr-1.5 h-3.5 w-3.5" />
                    Select
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setTrendsSortDir((d) => (d === "desc" ? "asc" : "desc"))
                    }
                    title={
                      trendsSortDir === "desc"
                        ? "Newest first — click to switch to oldest first"
                        : "Oldest first — click to switch to newest first"
                    }
                  >
                    {trendsSortDir === "desc" ? (
                      <ArrowDown className="mr-1.5 h-3.5 w-3.5" />
                    ) : (
                      <ArrowUp className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    Date
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleRefreshTrends}
                    disabled={refreshingTrends}
                    title="Run the pull + scoring cycle now (managers+)"
                  >
                    {refreshingTrends ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <TrendingUp className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    {refreshingTrends ? "Refreshing..." : "Refresh now"}
                  </Button>
                </>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {displayedTrends.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              {localTrendOnly
                ? "No local (Mauritius) trends yet."
                : "No trending topics yet."}
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {displayedTrends.map((trend) => (
                <TrendCard
                  key={trend.id}
                  trend={trend}
                  selectMode={trendsSelectMode}
                  selected={selectedTrendIds.has(trend.id)}
                  onToggleSelect={() => toggleTrendSelect(trend.id)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function velocityIcon(v: TrendData["velocity"]): string {
  if (v === "rising") return "↑";
  if (v === "falling") return "↓";
  return "→";
}

function velocityClass(v: TrendData["velocity"]): string {
  if (v === "rising") return "text-emerald-600 dark:text-emerald-400";
  if (v === "falling") return "text-rose-600 dark:text-rose-400";
  return "text-muted-foreground";
}

const GEO_FLAGS: Record<string, string> = {
  US: "🇺🇸",
  GB: "🇬🇧",
  FR: "🇫🇷",
  IN: "🇮🇳",
  JP: "🇯🇵",
  ZA: "🇿🇦",
  MU: "🇲🇺",
};

function geoBadge(geo: string | null | undefined): { flag: string; label: string } | null {
  if (!geo) return null;
  const code = geo.toUpperCase();
  return { flag: GEO_FLAGS[code] ?? "🌐", label: code };
}

function TrendCard({
  trend,
  selectMode,
  selected,
  onToggleSelect,
}: {
  trend: TrendData;
  selectMode: boolean;
  selected: boolean;
  onToggleSelect: () => void;
}) {
  const router = useRouter();

  const openInNewContent = () => {
    const params = new URLSearchParams({
      brand_id: trend.brand_id,
      title: trend.topic,
      description: trend.llm_angle || trend.relevance_reason || trend.topic,
      origin: "trend",
    });
    router.push(`/content?${params.toString()}`);
  };

  const handleClick = () => {
    if (selectMode) onToggleSelect();
    else openInNewContent();
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`group flex flex-col gap-2 rounded-md border p-3 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-primary ${
        selectMode && selected
          ? "border-primary bg-primary/5"
          : "hover:bg-accent hover:border-primary/50"
      }`}
      title={
        selectMode
          ? selected
            ? "Click to deselect"
            : "Click to select"
          : trend.relevance_reason || "Click to draft a post"
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 flex-1 min-w-0">
          {selectMode && (
            selected ? (
              <CheckSquare
                className="mt-0.5 h-4 w-4 shrink-0 text-primary"
                aria-hidden="true"
              />
            ) : (
              <Square
                className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground/50"
                aria-hidden="true"
              />
            )
          )}
          <p className="text-sm font-medium leading-tight flex-1 min-w-0">
            {trend.topic}
          </p>
        </div>
        <span
          className={`text-base font-semibold shrink-0 ${velocityClass(trend.velocity)}`}
          aria-label={`Velocity: ${trend.velocity}`}
        >
          {velocityIcon(trend.velocity)}
        </span>
      </div>

      {trend.llm_angle && (
        <p className="text-xs text-muted-foreground line-clamp-2">{trend.llm_angle}</p>
      )}

      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1.5">
          {(() => {
            const g = geoBadge(trend.geo);
            return g ? (
              <Badge
                variant="outline"
                className="text-[10px] gap-1"
                title={`Trending in ${g.label}`}
              >
                <span>{g.flag}</span>
                <span>{g.label}</span>
              </Badge>
            ) : null;
          })()}
          <Badge
            variant="secondary"
            className="text-[10px] bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-300"
          >
            {trend.brand_name}
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="text-[10px] text-muted-foreground"
            title={new Date(trend.discovered_at).toLocaleString("en-GB", {
              timeZone: "Indian/Mauritius",
              dateStyle: "medium",
              timeStyle: "short",
            })}
          >
            {formatRelativeTime(trend.discovered_at)}
          </span>
          <Badge variant="outline" className="text-[10px]">
            {trend.relevance_score}
          </Badge>
        </div>
      </div>
    </button>
  );
}
