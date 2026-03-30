"use client";

import dynamic from "next/dynamic";
import React from "react";

interface DataPoint {
  date: string;
  likes: number;
  comments: number;
  shares: number;
  impressions: number;
  engagement_rate: number;
}

export interface EngagementChartProps {
  data: DataPoint[];
}

const EngagementChartInner = dynamic(
  () => import("./EngagementChartInner").then((mod) => mod.EngagementChartInner),
  {
    ssr: false,
    loading: () => (
      <div className="h-[350px] flex items-center justify-center text-sm text-muted-foreground">
        Loading chart...
      </div>
    ),
  }
);

export function EngagementChart({ data }: EngagementChartProps) {
  return <EngagementChartInner data={data} />;
}
