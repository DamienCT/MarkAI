"use client";

import React from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart3 } from "lucide-react";
import type { ReportChartsProps } from "./ReportCharts";

const PRIORITY_COLORS: Record<string, string> = {
  High: "hsl(0 72% 51%)",
  Medium: "hsl(38 92% 50%)",
  Low: "hsl(142 76% 36%)",
};
const NEUTRAL = "var(--primary)";

interface Datum {
  name: string;
  value: number;
  color?: string;
}

/** A single annotated horizontal bar chart with a caption explaining how to
 *  read it — written so a non-marketing reader understands at a glance. */
function ChartBlock({
  title,
  caption,
  data,
}: {
  title: string;
  caption: string;
  data: Datum[];
}) {
  if (!data.length) return null;
  const height = Math.max(160, data.length * 44 + 40);
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold">{title}</h4>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 5, right: 24, left: 8, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--muted)" horizontal={false} />
            <XAxis
              type="number"
              allowDecimals={false}
              tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={140}
              tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: "8px",
                color: "var(--foreground)",
              }}
            />
            <Bar dataKey="value" radius={[0, 4, 4, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.color || NEUTRAL} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted-foreground italic">{caption}</p>
    </div>
  );
}

export function ReportChartsInner({ agentType, output }: ReportChartsProps) {
  const blocks: React.ReactNode[] = [];

  if (agentType === "research") {
    const gaps = Array.isArray(output.gaps) ? output.gaps : [];
    const buckets: Record<string, number> = { High: 0, Medium: 0, Low: 0 };
    for (const g of gaps) {
      const p = String((g as { priority?: string })?.priority || "").toLowerCase();
      if (p === "high" || p === "critical") buckets.High += 1;
      else if (p === "medium") buckets.Medium += 1;
      else if (p === "low") buckets.Low += 1;
    }
    const data: Datum[] = (["High", "Medium", "Low"] as const)
      .map((k) => ({ name: k, value: buckets[k], color: PRIORITY_COLORS[k] }))
      .filter((d) => d.value > 0);
    if (data.length) {
      blocks.push(
        <ChartBlock
          key="gaps"
          title="Opportunities by priority"
          caption="Each opportunity (a gap in the market the brand could fill) sorted by how urgent it is. Longer bar = more opportunities at that priority."
          data={data}
        />
      );
    }
  }

  if (agentType === "strategy") {
    const pillars = Array.isArray(output.content_pillars) ? output.content_pillars : [];
    const data: Datum[] = pillars
      .map((p) => {
        const obj = (typeof p === "object" && p) ? (p as Record<string, unknown>) : {};
        const name = String(obj.name || obj.title || "Pillar");
        const topics = Array.isArray(obj.topics) ? obj.topics.length : 0;
        const types = Array.isArray(obj.content_types) ? obj.content_types.length : 0;
        return { name, value: topics || types };
      })
      .filter((d) => d.value > 0);
    if (data.length) {
      blocks.push(
        <ChartBlock
          key="pillars"
          title="Topics per content pillar"
          caption="A content pillar is a recurring theme the brand posts about. This shows how many distinct topics each pillar covers — wider coverage = more to talk about."
          data={data}
        />
      );
    }
  }

  if (agentType === "planning") {
    const items = Array.isArray(output.calendar_items) ? output.calendar_items : [];
    const counts: Record<string, number> = {};
    for (const it of items) {
      const obj = (typeof it === "object" && it) ? (it as Record<string, unknown>) : {};
      const ch = String(obj.platform || obj.channel || "other");
      counts[ch] = (counts[ch] || 0) + 1;
    }
    const data: Datum[] = Object.entries(counts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
    if (data.length) {
      blocks.push(
        <ChartBlock
          key="channels"
          title="Planned posts per channel"
          caption="How many pieces of content are scheduled on each platform. Longer bar = more posts planned there."
          data={data}
        />
      );
    }
  }

  if (agentType === "content_calendar" || agentType === "content_calendar_strategy") {
    const themes = Array.isArray(output.monthly_themes) ? output.monthly_themes : [];
    const data: Datum[] = themes
      .map((t) => {
        const obj = (typeof t === "object" && t) ? (t as Record<string, unknown>) : {};
        const name = String(obj.month || obj.name || "Month");
        const focus = Array.isArray(obj.focus_areas) ? obj.focus_areas.length : 0;
        return { name, value: focus };
      })
      .filter((d) => d.value > 0);
    if (data.length) {
      blocks.push(
        <ChartBlock
          key="themes"
          title="Focus areas per month"
          caption="How many distinct focus areas are planned each month across the year. Longer bar = a busier month."
          data={data}
        />
      );
    }
  }

  if (!blocks.length) return null;

  return (
    <Card className="print-break" id="section-charts">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-primary" />
          At a Glance
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          The numbers from this report, visualized.
        </p>
      </CardHeader>
      <CardContent className="space-y-8">{blocks}</CardContent>
    </Card>
  );
}
