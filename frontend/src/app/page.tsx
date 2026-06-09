"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Building2,
  CheckSquare,
  FileText,
  Clock,
  Loader2,
  ArrowRight,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { api } from "@/lib/api";
import { statusColor } from "@/lib/utils";
import type { DashboardStats, ActiveAgentRun, CalendarItem } from "@/types";

type ChartData = {
  days: number;
  published_per_day: { day: string; count: number }[];
  published_by_channel: { channel: string; count: number }[];
};

const CHART_DAY_OPTIONS = [30, 60, 90, 120];

// Brand colors for the known channels; anything else cycles a neutral palette.
const CHANNEL_COLORS: Record<string, string> = {
  instagram: "#E1306C",
  facebook: "#1877F2",
  linkedin: "#0A66C2",
  twitter: "#1DA1F2",
  tiktok: "#111827",
};
const FALLBACK_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];
const CHART_COLOR = "#6366f1"; // line/area accent for the published-per-day chart
function channelColor(channel: string, i: number): string {
  return CHANNEL_COLORS[(channel || "").toLowerCase()] ?? FALLBACK_COLORS[i % FALLBACK_COLORS.length];
}

// "2026-06-08" -> "8 Jun" for compact x-axis ticks.
function shortDay(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

// Group an upcoming calendar item under a human day header (Today / Tomorrow / date).
function dayLabel(iso: string | null): string {
  if (!iso) return "Unscheduled";
  const d = new Date(iso);
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (sameDay(d, today)) return "Today";
  if (sameDay(d, tomorrow)) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function timeLabel(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [activeWorkflows, setActiveWorkflows] = useState<ActiveAgentRun[]>([]);
  const [calendarItems, setCalendarItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [charts, setCharts] = useState<ChartData | null>(null);
  const [chartDays, setChartDays] = useState(30);
  const [chartsLoading, setChartsLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchDashboard() {
      try {
        const [dashData, runsData, postsData] = await Promise.allSettled([
          api.get<DashboardStats>("/api/v1/dashboard/stats", undefined, { signal }),
          api.get<ActiveAgentRun[]>("/api/v1/agents/runs/active", undefined, { signal }),
          api.get<CalendarItem[]>("/api/v1/calendar/upcoming", { limit: 12 }, { signal }),
        ]);

        if (dashData.status === "fulfilled") setStats(dashData.value);
        if (runsData.status === "fulfilled" && Array.isArray(runsData.value)) setActiveWorkflows(runsData.value);
        if (postsData.status === "fulfilled" && Array.isArray(postsData.value)) setCalendarItems(postsData.value);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError("Failed to load dashboard data");
      } finally {
        setLoading(false);
      }
    }
    fetchDashboard();

    return () => controller.abort();
  }, []);

  // Charts are fetched separately so changing the day window only refetches them.
  useEffect(() => {
    const controller = new AbortController();
    setChartsLoading(true);
    api
      .get<ChartData>("/api/v1/dashboard/charts", { days: chartDays }, { signal: controller.signal })
      .then((d) => setCharts(d))
      .catch((err) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
      })
      .finally(() => setChartsLoading(false));
    return () => controller.abort();
  }, [chartDays]);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Dashboard Control</h1>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <p className="text-lg text-muted-foreground">{error}</p>
          <p className="text-sm text-muted-foreground mt-1">Make sure the API backend is running.</p>
        </div>
      </div>
    );
  }

  const statCards = [
    {
      title: "Active Brands",
      value: stats?.active_brands ?? 0,
      icon: Building2,
      href: "/brands",
    },
    {
      title: "Pending Approvals",
      value: stats?.pending_approvals ?? 0,
      icon: CheckSquare,
      href: "/approvals",
    },
    {
      title: "Content in Pipeline",
      value: stats?.content_in_pipeline ?? 0,
      icon: FileText,
      href: "/content",
    },
    {
      title: "Scheduled Posts",
      value: stats?.scheduled_posts ?? 0,
      icon: Clock,
      href: "/content/calendar",
    },
  ];

  const groupedCalendar = calendarItems.reduce<Record<string, CalendarItem[]>>((acc, item) => {
    const label = dayLabel(item.scheduled_at);
    (acc[label] ||= []).push(item);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Dashboard Control</h1>
        <Badge variant="outline" className="text-sm">
          Published this week: {stats?.published_this_week ?? 0}
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Link key={stat.title} href={stat.href}>
            <Card className="hover:shadow-md transition-shadow cursor-pointer">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardDescription>{stat.title}</CardDescription>
                <stat.icon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{stat.value}</div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 lg:items-stretch">
        {/* LEFT COLUMN: charts on top, active workflows below */}
        <div className="lg:col-span-2 flex flex-col gap-6 min-h-0">
          {/* Top row: 70% line chart + 30% donut */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-10">
            <Card className="lg:col-span-7 flex flex-col">
              <CardHeader className="flex flex-row items-center justify-between gap-2 pb-2">
                <div>
                  <CardTitle className="text-lg">Published Posts</CardTitle>
                  <CardDescription>Per day · last {chartDays} days</CardDescription>
                </div>
                <div className="flex gap-1">
                  {CHART_DAY_OPTIONS.map((d) => (
                    <Button
                      key={d}
                      variant={chartDays === d ? "default" : "outline"}
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => setChartDays(d)}
                    >
                      {d}d
                    </Button>
                  ))}
                </div>
              </CardHeader>
              <CardContent>
                <div className="h-[220px] w-full">
                  {chartsLoading && !charts ? (
                    <Skeleton className="h-full w-full" />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={charts?.published_per_day ?? []}
                        margin={{ top: 5, right: 12, left: -18, bottom: 0 }}
                      >
                        <defs>
                          <linearGradient id="pubGradient" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor={CHART_COLOR} stopOpacity={0.35} />
                            <stop offset="95%" stopColor={CHART_COLOR} stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                        <XAxis
                          dataKey="day"
                          tickFormatter={shortDay}
                          tick={{ fontSize: 11 }}
                          minTickGap={24}
                        />
                        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
                        <Tooltip
                          labelFormatter={(v) => shortDay(String(v))}
                          formatter={(value) => [value, "Published"]}
                        />
                        <Area
                          type="monotone"
                          dataKey="count"
                          stroke={CHART_COLOR}
                          strokeWidth={2}
                          fill="url(#pubGradient)"
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="lg:col-span-3 flex flex-col">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg">Published by Channel</CardTitle>
                <CardDescription>This month</CardDescription>
              </CardHeader>
              <CardContent className="flex-1">
                {chartsLoading && !charts ? (
                  <Skeleton className="h-[220px] w-full" />
                ) : (charts?.published_by_channel?.length ?? 0) === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-16">
                    No posts published this month
                  </p>
                ) : (
                  <div className="h-[220px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={charts?.published_by_channel ?? []}
                          dataKey="count"
                          nameKey="channel"
                          innerRadius={42}
                          outerRadius={72}
                          paddingAngle={2}
                        >
                          {(charts?.published_by_channel ?? []).map((entry, i) => (
                            <Cell key={entry.channel} fill={channelColor(entry.channel, i)} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value, name) => [value, name]} />
                        <Legend
                          verticalAlign="bottom"
                          height={24}
                          iconSize={8}
                          formatter={(v) => <span className="text-xs capitalize">{v}</span>}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Bottom: Active Workflows (scrolls so the column never exceeds the calendar) */}
          <Card className="flex-1 min-h-0 flex flex-col">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <div>
                <CardTitle className="text-lg">Active Workflows</CardTitle>
                <CardDescription>AI pipelines running right now</CardDescription>
              </div>
              <Link href="/system" className="text-sm text-primary hover:underline flex items-center gap-1">
                View system <ArrowRight className="h-3 w-3" />
              </Link>
            </CardHeader>
            <CardContent className="flex-1 min-h-0 overflow-y-auto">
            {activeWorkflows.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No active workflows right now
              </p>
            ) : (
              <div className="space-y-3">
                {activeWorkflows.map((run) => {
                  const total = run.total_steps && run.total_steps > 0 ? run.total_steps : 10;
                  const idx = run.step_index ?? 0;
                  const pct = Math.min(100, Math.round((idx / total) * 100));
                  return (
                    <div key={run.id} className="rounded-md border p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-3 min-w-0">
                          <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
                          <div className="min-w-0">
                            <p className="text-sm font-medium truncate capitalize">
                              {run.agent_type.replace(/_/g, " ")}
                            </p>
                            <p className="text-xs text-muted-foreground truncate">
                              {run.current_step || "Working..."}
                            </p>
                          </div>
                        </div>
                        <span className="text-xs text-muted-foreground shrink-0">
                          {idx}/{total}
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full bg-primary transition-all"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            </CardContent>
          </Card>
        </div>

        {/* RIGHT COLUMN: Content Calendar — sets the overall column height */}
        <Card className="lg:col-span-1 flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <div>
              <CardTitle className="text-lg">Content Calendar</CardTitle>
              <CardDescription>What&apos;s coming up next</CardDescription>
            </div>
            <Link href="/content/calendar" className="text-sm text-primary hover:underline flex items-center gap-1">
              Open calendar <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto">
            {calendarItems.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                Nothing on the calendar yet
              </p>
            ) : (
              <div className="space-y-4">
                {Object.entries(groupedCalendar).map(([label, items]) => (
                  <div key={label}>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      {label}
                    </p>
                    <div className="space-y-2">
                      {items.map((item) => (
                        <div
                          key={item.id}
                          className="flex items-center justify-between gap-3 rounded-md border p-2.5"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="text-xs font-mono text-muted-foreground w-12 shrink-0">
                              {timeLabel(item.scheduled_at)}
                            </span>
                            <div className="min-w-0">
                              <p className="text-sm font-medium truncate">{item.title}</p>
                              <p className="text-xs text-muted-foreground capitalize">{item.channel}</p>
                            </div>
                          </div>
                          <Badge className={statusColor(item.status)} variant="outline">
                            {item.status}
                          </Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
