"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Globe, ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import type { Competitor } from "@/types";

interface CompetitorTrackerProps {
  brandId: string;
  competitors: Competitor[];
}

interface CompetitorInsight {
  competitor_name: string;
  recent_posts: number;
  avg_engagement: number;
  trending_topics: string[];
  last_updated: string;
}

export function CompetitorTracker({ brandId, competitors }: CompetitorTrackerProps) {
  const [insights, setInsights] = useState<CompetitorInsight[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchInsights() {
      try {
        const data = await api.get<CompetitorInsight[]>(
          `/api/v1/intelligence/brands/${brandId}/competitors`
        );
        setInsights(data);
      } catch {
        // Handle error
      } finally {
        setLoading(false);
      }
    }
    fetchInsights();
  }, [brandId]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Competitor Tracking</CardTitle>
          <CardDescription>Monitor competitor activity and performance</CardDescription>
        </CardHeader>
        <CardContent>
          {competitors.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              No competitors configured for this brand
            </p>
          ) : (
            <div className="space-y-4">
              {competitors.map((competitor, i) => {
                const insight = insights.find(
                  (ins) => ins.competitor_name.toLowerCase() === competitor.name.toLowerCase()
                );
                return (
                  <div key={i} className="rounded-md border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <h4 className="font-medium">{competitor.name}</h4>
                        {competitor.website_url && (
                          <a
                            href={competitor.website_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-muted-foreground hover:text-foreground"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                      <div className="flex gap-1">
                        {Object.entries(competitor.social_handles).map(([platform, handle]) => (
                          <Badge key={platform} variant="outline" className="text-[10px] capitalize">
                            {platform}: @{handle}
                          </Badge>
                        ))}
                      </div>
                    </div>

                    {insight && (
                      <div className="grid grid-cols-2 gap-4 text-sm">
                        <div>
                          <p className="text-muted-foreground">Recent Posts</p>
                          <p className="font-medium">{insight.recent_posts}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Avg Engagement</p>
                          <p className="font-medium">{(insight.avg_engagement * 100).toFixed(2)}%</p>
                        </div>
                        {insight.trending_topics.length > 0 && (
                          <div className="col-span-2">
                            <p className="text-muted-foreground mb-1">Trending Topics</p>
                            <div className="flex flex-wrap gap-1">
                              {insight.trending_topics.map((topic, j) => (
                                <Badge key={j} variant="secondary" className="text-xs">
                                  {topic}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {competitor.notes && (
                      <p className="text-xs text-muted-foreground">{competitor.notes}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
