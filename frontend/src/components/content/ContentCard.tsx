"use client";

import React from "react";
import Link from "next/link";
import { Calendar, FileText } from "lucide-react";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import { STATUS_COLORS } from "@/lib/constants";
import type { CalendarItem } from "@/types";

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued", working: "Working", in_review: "In Review",
  reworking: "Reworking", approved: "Approved", scheduled: "Scheduled",
  published: "Published", failed: "Failed",
};

interface ContentCardProps {
  item: CalendarItem;
}

export function ContentCard({ item }: ContentCardProps) {
  return (
    <Link href={`/content/${item.id}`}>
      <Card className="hover:shadow-md transition-shadow cursor-pointer h-full flex flex-col">
        <div className="aspect-video w-full rounded-t-lg bg-muted flex items-center justify-center">
          <FileText className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardContent className="pt-4 flex-1">
          <div className="flex items-center justify-between mb-2 gap-2">
            <Badge className={STATUS_COLORS[item.status] || ""} variant="outline">
              {STATUS_LABELS[item.status] || item.status}
            </Badge>
            {item.channel && (
              <Badge variant="outline" className="capitalize text-xs">
                {item.channel}
              </Badge>
            )}
          </div>
          <h3 className="font-medium text-sm line-clamp-2">{item.title || "Untitled"}</h3>
          {item.brand_name && (
            <p className="text-xs text-primary/70 mt-0.5">{item.brand_name}</p>
          )}
          {item.description && (
            <p className="text-xs text-muted-foreground line-clamp-2 mt-1">{item.description}</p>
          )}
        </CardContent>
        <CardFooter className="pt-0">
          {item.scheduled_at && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Calendar className="h-3 w-3" />
              {formatDate(item.scheduled_at)}
            </div>
          )}
        </CardFooter>
      </Card>
    </Link>
  );
}
