"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Building2,
  CheckSquare,
  FileText,
  Clock,
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
} from "recharts";
import { api } from "@/lib/api";
import { cn, statusColor } from "@/lib/utils";
import type { DashboardStats, CalendarItem } from "@/types";

type ChartData = {
  days: number;
  channels: string[];
  // Wide rows: { day: "2026-06-05", instagram: 2, facebook: 1, ... }
  published_per_day: Record<string, number | string>[];
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
  const [calendarItems, setCalendarItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [charts, setCharts] = useState<ChartData | null>(null);
  const [chartDays, setChartDays] = useState(30);
  const [chartsLoading, setChartsLoading] = useState(true);
  const [hiddenChannels, setHiddenChannels] = useState<Set<string>>(new Set());

  const toggleChannel = (ch: string) =>
    setHiddenChannels((prev) => {
      const next = new Set(prev);
      if (next.has(ch)) next.delete(ch);
      else next.add(ch);
      return next;
    });

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchDashboard() {
      try {
        const [dashData, postsData] = await Promise.allSettled([
          api.get<DashboardStats>("/api/v1/dashboard/stats", undefined, { signal }),
          api.get<CalendarItem[]>("/api/v1/calendar/upcoming", { limit: 12 }, { signal }),
        ]);

        if (dashData.status === "fulfilled") setStats(dashData.value);
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
      href: "/content/stage/in_review",
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

  // Dashboard widget shows only the next 3 days that have content (skip any
  // "Unscheduled" group); groups are already in chronological order.
  const visibleCalendar = Object.entries(groupedCalendar)
    .filter(([label]) => label !== "Unscheduled")
    .slice(0, 3);


  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Dashboard Control</h1>

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
              <CardContent className="flex-1">
                {/* Legend doubles as a per-channel filter — click to show/hide */}
                {(charts?.channels?.length ?? 0) > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    {(charts?.channels ?? []).map((ch, i) => {
                      const hidden = hiddenChannels.has(ch);
                      return (
                        <button
                          key={ch}
                          type="button"
                          onClick={() => toggleChannel(ch)}
                          className={cn(
                            "flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition",
                            hidden ? "opacity-40" : "hover:bg-accent"
                          )}
                        >
                          <span
                            className="h-2.5 w-2.5 rounded-full"
                            style={{ background: channelColor(ch, i) }}
                          />
                          <span className="capitalize">{ch}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
                <div className="h-[200px] w-full">
                  {chartsLoading && !charts ? (
                    <Skeleton className="h-full w-full" />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={charts?.published_per_day ?? []}
                        margin={{ top: 5, right: 12, left: 0, bottom: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                        <XAxis
                          dataKey="day"
                          tickFormatter={shortDay}
                          tick={{ fontSize: 11 }}
                          minTickGap={24}
                        />
                        <YAxis
                          allowDecimals={false}
                          tick={{ fontSize: 11 }}
                          width={32}
                          domain={[0, "auto"]}
                        />
                        <Tooltip labelFormatter={(v) => shortDay(String(v))} />
                        {(charts?.channels ?? []).map((ch, i) => (
                          <Area
                            key={ch}
                            type="linear"
                            dataKey={ch}
                            name={ch}
                            stroke={channelColor(ch, i)}
                            strokeWidth={2}
                            fill={channelColor(ch, i)}
                            fillOpacity={0.25}
                            hide={hiddenChannels.has(ch)}
                            dot={false}
                            activeDot={{ r: 4 }}
                          />
                        ))}
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="lg:col-span-3 flex flex-col">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg">Monthly Goal</CardTitle>
                <CardDescription>Published vs target this month</CardDescription>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col items-center justify-center">
                {(() => {
                  const published = stats?.monthly_goal?.published ?? 0;
                  const target = stats?.monthly_goal?.target ?? 0;
                  const pct = target > 0 ? Math.round((published / target) * 100) : 0;
                  const done = target > 0 ? Math.min(published, target) : 0;
                  const remaining = Math.max(target - published, 0);
                  if (target === 0) {
                    return (
                      <div className="text-center py-10">
                        <p className="text-3xl font-bold">{published}</p>
                        <p className="text-sm text-muted-foreground mt-1">
                          published this month
                        </p>
                        <p className="text-xs text-muted-foreground mt-2">
                          No strategy cadence set
                        </p>
                      </div>
                    );
                  }
                  return (
                    <>
                      <div className="relative h-[170px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={[
                                { name: "done", value: done },
                                { name: "remaining", value: remaining },
                              ]}
                              dataKey="value"
                              innerRadius={55}
                              outerRadius={75}
                              startAngle={90}
                              endAngle={-270}
                              stroke="none"
                            >
                              <Cell fill="#6366f1" />
                              <Cell fill="#e5e7eb" />
                            </Pie>
                          </PieChart>
                        </ResponsiveContainer>
                        <div className="absolute inset-0 flex items-center justify-center">
                          <span className="text-3xl font-bold">{pct}%</span>
                        </div>
                      </div>
                      <p className="text-sm text-muted-foreground mt-1">
                        {published} / {target} published
                      </p>
                    </>
                  );
                })()}
              </CardContent>
            </Card>
          </div>

          {/* Bottom: Active Workflows summary — running / completed / failed */}
          <Card className="flex-1 min-h-0 flex flex-col">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <div>
                <CardTitle className="text-lg">Active Workflows</CardTitle>
                <CardDescription>Running, completed, and failed</CardDescription>
              </div>
              <Link href="/system" className="text-sm text-primary hover:underline flex items-center gap-1">
                View system <ArrowRight className="h-3 w-3" />
              </Link>
            </CardHeader>
            <CardContent className="flex-1">
              <div className="grid h-full grid-cols-3 gap-3">
                {[
                  {
                    label: "Running / Pending",
                    value: stats?.workflows_running_pending ?? 0,
                    dot: "bg-blue-500",
                  },
                  {
                    label: "Completed",
                    value: stats?.workflows_completed ?? 0,
                    dot: "bg-green-500",
                  },
                  {
                    label: "Failed",
                    value: stats?.workflows_failed ?? 0,
                    dot: "bg-red-500",
                  },
                ].map((c) => (
                  <div
                    key={c.label}
                    className="flex flex-col justify-center rounded-md border p-4"
                  >
                    <div className="flex items-center gap-2">
                      <span className={cn("h-2.5 w-2.5 rounded-full", c.dot)} />
                      <span className="text-2xl font-bold">{c.value}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{c.label}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* RIGHT COLUMN: Content Calendar — sets the overall column height */}
        <Card className="lg:col-span-1 flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <div>
              <CardTitle className="text-lg">Content Calendar</CardTitle>
              <CardDescription>Next 3 days</CardDescription>
            </div>
            <Link href="/content/calendar" className="text-sm text-primary hover:underline flex items-center gap-1">
              Open calendar <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto">
            {visibleCalendar.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                Nothing on the calendar yet
              </p>
            ) : (
              <div className="space-y-4">
                {visibleCalendar.map(([label, items]) => (
                  <div key={label}>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      {label}
                    </p>
                    <div className="space-y-2">
                      {items.map((item) => (
                        <Link
                          key={item.id}
                          href={`/content/${item.id}`}
                          className="flex items-center justify-between gap-3 rounded-md border p-2.5 transition-colors hover:bg-accent cursor-pointer"
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
                        </Link>
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
