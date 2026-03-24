"use client";

import React from "react";
import Link from "next/link";
import { Calendar, FileText } from "lucide-react";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import type { CalendarItem } from "@/types";

const STATUS_COLORS: Record<string, string> = {
  queued: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200",
  working: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200",
  in_review: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  reworking: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  approved: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200",
  scheduled: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  published: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

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
