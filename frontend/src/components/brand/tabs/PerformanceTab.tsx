"use client";

import React from "react";
import { BarChart3 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { EngagementMetrics } from "@/types";

export interface PerformanceTabProps {
  metrics: EngagementMetrics | null;
}

export function PerformanceTab({ metrics }: PerformanceTabProps) {
  return (
    <div className="mt-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Performance Analytics</CardTitle>
          <CardDescription>Engagement and content performance data</CardDescription>
        </CardHeader>
        <CardContent>
          {metrics ? (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="rounded-lg border p-4 text-center">
                <p className="text-2xl font-bold">{metrics.reach.toLocaleString()}</p>
                <p className="text-sm text-muted-foreground">Reach</p>
              </div>
              <div className="rounded-lg border p-4 text-center">
                <p className="text-2xl font-bold">{metrics.impressions.toLocaleString()}</p>
                <p className="text-sm text-muted-foreground">Impressions</p>
              </div>
              <div className="rounded-lg border p-4 text-center">
                <p className="text-2xl font-bold">{(metrics.engagement_rate * 100).toFixed(2)}%</p>
                <p className="text-sm text-muted-foreground">Engagement Rate</p>
              </div>
              <div className="rounded-lg border p-4 text-center">
                <p className="text-2xl font-bold">{metrics.shares.toLocaleString()}</p>
                <p className="text-sm text-muted-foreground">Shares</p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-8 space-y-2">
              <BarChart3 className="h-10 w-10 text-muted-foreground/30" />
              <p className="text-sm text-muted-foreground">No performance data available yet</p>
              <p className="text-xs text-muted-foreground">Analytics will populate once content starts getting published and engagement is tracked.</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
