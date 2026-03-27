"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";
import { FileText } from "lucide-react";

interface ResearchReport {
  id: string;
  brand_id: string;
  brand_name?: string;
  report_type: string;
  title: string;
  summary: string;
  insights: string[];
  created_at: string;
}

interface TrendData {
  id: string;
  topic: string;
  platform: string;
  relevance_score: number;
  description: string;
  discovered_at: string;
}

export default function IntelligencePage() {
  const router = useRouter();
  const [reports, setReports] = useState<ResearchReport[]>([]);
  const [trends, setTrends] = useState<TrendData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const [reportsData, trendsData] = await Promise.allSettled([
          api.get<ResearchReport[]>("/api/v1/intelligence/reports", { limit: 20 }),
          api.get<TrendData[]>("/api/v1/intelligence/trends", { limit: 20 }),
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
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Intelligence</h1>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Intelligence</h1>
        <p className="text-muted-foreground">Research, trends, and competitor insights</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Research Reports</CardTitle>
            <CardDescription>Latest research and analysis</CardDescription>
          </CardHeader>
          <CardContent>
            {reports.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">No research reports available</p>
            ) : (
              <div className="space-y-4">
                {reports.map((report) => (
                  <div
                    key={report.id}
                    className="rounded-md border p-4 space-y-2 cursor-pointer hover:bg-muted/50 hover:border-primary/30 transition-colors group"
                    onClick={() => router.push(`/intelligence/report/${report.id}`)}
                  >
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-medium group-hover:text-primary transition-colors flex items-center gap-1.5">
                        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground group-hover:text-primary" />
                        {report.title}
                      </h3>
                      <Badge variant="outline">{report.report_type}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{report.summary}</p>
                    {report.insights && report.insights.length > 0 && (
                      <ul className="text-xs text-muted-foreground space-y-1">
                        {report.insights.slice(0, 3).map((insight, i) => (
                          <li key={i} className="flex items-start gap-1">
                            <span className="text-primary mt-0.5">-</span>
                            {insight}
                          </li>
                        ))}
                      </ul>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {formatRelativeTime(report.created_at)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Trending Topics</CardTitle>
            <CardDescription>Current trends and emerging topics</CardDescription>
          </CardHeader>
          <CardContent>
            {trends.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">No trending topics detected</p>
            ) : (
              <div className="space-y-3">
                {trends.map((trend) => (
                  <div key={trend.id} className="flex items-center justify-between rounded-md border p-3">
                    <div>
                      <p className="text-sm font-medium">{trend.topic}</p>
                      <p className="text-xs text-muted-foreground capitalize">{trend.platform}</p>
                    </div>
                    <div className="text-right">
                      <Badge variant="outline">
                        {Math.round(trend.relevance_score * 100)}% relevant
                      </Badge>
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
