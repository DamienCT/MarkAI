"use client";

import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EngagementChart } from "@/components/analytics/EngagementChart";
import { PostingHeatmap } from "@/components/analytics/PostingHeatmap";
import { api } from "@/lib/api";
import type { Brand } from "@/types";

interface AnalyticsSummary {
  impressions: number;
  likes: number;
  comments: number;
  shares: number;
  reach: number;
  clicks: number;
  engagement_rate: number;
  total_published_posts: number;
}

interface AnalyticsTimeSeries {
  date: string;
  likes: number;
  comments: number;
  shares: number;
  impressions: number;
  engagement_rate: number;
}

interface HeatmapData {
  day: number;
  hour: number;
  count: number;
}

interface TopContent {
  id: string;
  title: string;
  channel: string;
  status: string;
  likes: number;
  comments: number;
  shares: number;
  impressions: number;
  engagement_rate: number;
}

const DATE_PRESETS = [
  { label: "7d", value: 7 },
  { label: "30d", value: 30 },
  { label: "90d", value: 90 },
] as const;

export default function AnalyticsPage() {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [selectedBrandId, setSelectedBrandId] = useState<string>("all");
  const [days, setDays] = useState<number>(30);
  const [timeSeries, setTimeSeries] = useState<AnalyticsTimeSeries[]>([]);
  const [heatmapData, setHeatmapData] = useState<HeatmapData[]>([]);
  const [topContent, setTopContent] = useState<TopContent[]>([]);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    async function fetchBrands() {
      try {
        const data = await api.get<Brand[]>("/api/v1/brands", undefined, { signal: controller.signal });
        setBrands(data);
      } catch {
        // Brands may fail silently; analytics still loads for "all"
      }
    }
    fetchBrands();
    return () => controller.abort();
  }, []);

  const fetchAnalytics = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { days };
      if (selectedBrandId !== "all") {
        params.brand_id = selectedBrandId;
      }

      const [tsData, hmData, contentData, summaryData] = await Promise.allSettled([
        api.get<AnalyticsTimeSeries[]>("/api/v1/analytics/engagement/timeseries", params, { signal }),
        api.get<HeatmapData[]>("/api/v1/analytics/posting/heatmap", params, { signal }),
        api.get<TopContent[]>("/api/v1/analytics/content/top", { ...params, limit: 10 }, { signal }),
        api.get<AnalyticsSummary>("/api/v1/analytics/summary", params, { signal }),
      ]);
      if (tsData.status === "fulfilled") setTimeSeries(tsData.value);
      else setTimeSeries([]);
      if (hmData.status === "fulfilled") setHeatmapData(hmData.value);
      else setHeatmapData([]);
      if (contentData.status === "fulfilled") setTopContent(contentData.value);
      else setTopContent([]);
      if (summaryData.status === "fulfilled") setSummary(summaryData.value);
      else setSummary(null);
    } catch {
      toast.error("Failed to load analytics data");
    } finally {
      setLoading(false);
    }
  }, [selectedBrandId, days]);

  useEffect(() => {
    const controller = new AbortController();
    fetchAnalytics(controller.signal);
    return () => controller.abort();
  }, [fetchAnalytics]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold">Analytics</h1>
          <p className="text-muted-foreground">Performance dashboards and insights</p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={selectedBrandId} onValueChange={setSelectedBrandId}>
            <SelectTrigger className="w-[200px]">
              <SelectValue placeholder="All Brands" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Brands</SelectItem>
              {brands.map((brand) => (
                <SelectItem key={brand.id} value={brand.id}>
                  {brand.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex rounded-md border">
            {DATE_PRESETS.map((preset) => (
              <Button
                key={preset.value}
                variant={days === preset.value ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setDays(preset.value)}
              >
                {preset.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-80" />
        </>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Total Impressions</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold">{(summary?.impressions ?? 0).toLocaleString()}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Engagement Rate</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold">{((summary?.engagement_rate ?? 0) * 100).toFixed(2)}%</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Total Likes</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold">{(summary?.likes ?? 0).toLocaleString()}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Total Reach</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold">{(summary?.reach ?? 0).toLocaleString()}</p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Engagement Over Time</CardTitle>
              <CardDescription>Daily engagement metrics for the past {days} days</CardDescription>
            </CardHeader>
            <CardContent>
              {timeSeries.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-12">No engagement data available yet</p>
              ) : (
                <EngagementChart data={timeSeries} />
              )}
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Posting Heatmap</CardTitle>
                <CardDescription>Optimal posting times by day and hour</CardDescription>
              </CardHeader>
              <CardContent>
                {heatmapData.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-12">No posting data available yet</p>
                ) : (
                  <PostingHeatmap data={heatmapData} />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Top Performing Content</CardTitle>
                <CardDescription>Content ranked by engagement</CardDescription>
              </CardHeader>
              <CardContent>
                {topContent.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-12">No performance data available yet</p>
                ) : (
                  <div className="space-y-3">
                    {topContent.map((item, i) => (
                      <div key={item.id} className="flex items-center justify-between py-2 border-b last:border-0">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-bold text-muted-foreground w-6">{i + 1}</span>
                          <div>
                            <p className="text-sm font-medium line-clamp-1">{item.title || "Untitled"}</p>
                            <p className="text-xs text-muted-foreground capitalize">{item.channel}</p>
                          </div>
                        </div>
                        <div className="text-right text-xs text-muted-foreground">
                          <p>{(item.likes + item.comments + item.shares).toLocaleString()} engagements</p>
                          <p>{item.impressions.toLocaleString()} impressions</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
