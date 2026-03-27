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

interface DataPoint {
  date: string;
  likes: number;
  comments: number;
  shares: number;
  impressions: number;
  engagement_rate: number;
}

interface EngagementChartProps {
  data: DataPoint[];
}

export function EngagementChart({ data }: EngagementChartProps) {
  const formattedData = data.map((d) => ({
    ...d,
    dateLabel: format(parseISO(d.date), "MMM d"),
    engagement_pct: (d.engagement_rate * 100).toFixed(2),
  }));

  return (
    <div className="h-[350px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={formattedData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
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
            stroke="hsl(228, 76%, 59%)"
            strokeWidth={2}
            dot={false}
            name="Likes"
          />
          <Line
            type="monotone"
            dataKey="comments"
            stroke="hsl(142, 76%, 36%)"
            strokeWidth={2}
            dot={false}
            name="Comments"
          />
          <Line
            type="monotone"
            dataKey="shares"
            stroke="hsl(38, 92%, 50%)"
            strokeWidth={2}
            dot={false}
            name="Shares"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
