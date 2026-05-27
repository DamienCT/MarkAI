"use client";

import dynamic from "next/dynamic";

export interface ReportChartsProps {
  agentType: string;
  output: Record<string, unknown>;
}

// recharts' ResponsiveContainer needs a real DOM box, so render client-only.
const ReportChartsInner = dynamic(
  () => import("./ReportChartsInner").then((m) => m.ReportChartsInner),
  { ssr: false }
);

export function ReportCharts(props: ReportChartsProps) {
  return <ReportChartsInner {...props} />;
}
