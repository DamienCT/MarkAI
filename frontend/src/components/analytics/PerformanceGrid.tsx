"use client";

import React from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { statusColor } from "@/lib/utils";
import type { Content } from "@/types";

interface PerformanceGridProps {
  content: Content[];
}

export function PerformanceGrid({ content }: PerformanceGridProps) {
  return (
    <div className="space-y-2 max-h-[400px] overflow-y-auto">
      {content.map((item) => (
        <Link key={item.id} href={`/content/${item.id}`}>
          <div className="flex items-center justify-between rounded-md border p-3 hover:bg-accent/50 transition-colors cursor-pointer">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{item.title}</p>
              <div className="flex items-center gap-2 mt-1">
                <Badge variant="outline" className="text-[10px] capitalize">
                  {item.platform}
                </Badge>
                <Badge className={statusColor(item.status)} variant="outline">
                  {item.status}
                </Badge>
              </div>
            </div>
            {item.engagement_metrics && (
              <div className="flex gap-4 text-right ml-4">
                <div>
                  <p className="text-xs text-muted-foreground">Likes</p>
                  <p className="text-sm font-medium">{item.engagement_metrics.likes.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Comments</p>
                  <p className="text-sm font-medium">{item.engagement_metrics.comments.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Rate</p>
                  <p className="text-sm font-medium">
                    {(item.engagement_metrics.engagement_rate * 100).toFixed(1)}%
                  </p>
                </div>
              </div>
            )}
          </div>
        </Link>
      ))}
    </div>
  );
}
