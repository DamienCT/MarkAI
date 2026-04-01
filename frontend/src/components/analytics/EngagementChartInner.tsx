"use client";

import React from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { format, parseISO } from "date-fns";
import type { EngagementChartProps } from "./EngagementChart";

// ── Chart line colors ────────────────────────────────────────────────
const CHART_COLORS = {
  likes: "var(--primary)",                // App primary (blue)
  comments: "hsl(142 76% 36%)",           // Green — no semantic CSS variable available
  shares: "hsl(38 92% 50%)",              // Amber — no semantic CSS variable available
} as const;

export function EngagementChartInner({ data }: EngagementChartProps) {
  const formattedData = data.map((d) => ({
    ...d,
    dateLabel: format(parseISO(d.date), "MMM d"),
    engagement_pct: (d.engagement_rate * 100).toFixed(2),
  }));

  return (
    <div className="h-[350px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={formattedData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--muted)" />
          <XAxis
            dataKey="dateLabel"
            className="text-xs"
            tick={{ fill: "var(--muted-foreground)" }}
          />
          <YAxis
            className="text-xs"
            tick={{ fill: "var(--muted-foreground)" }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
              color: "var(--foreground)",
            }}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="likes"
            stroke={CHART_COLORS.likes}
            strokeWidth={2}
            dot={false}
            name="Likes"
          />
          <Line
            type="monotone"
            dataKey="comments"
            stroke={CHART_COLORS.comments}
            strokeWidth={2}
            dot={false}
            name="Comments"
          />
          <Line
            type="monotone"
            dataKey="shares"
            stroke={CHART_COLORS.shares}
            strokeWidth={2}
            dot={false}
            name="Shares"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
