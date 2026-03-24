"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface HeatmapData {
  day: number;
  hour: number;
  count: number;
}

interface PostingHeatmapProps {
  data: HeatmapData[];
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HOURS = Array.from({ length: 24 }, (_, i) => i);

export function PostingHeatmap({ data }: PostingHeatmapProps) {
  const maxCount = Math.max(...data.map((d) => d.count), 1);

  function getCount(day: number, hour: number): number {
    const item = data.find((d) => d.day === day && d.hour === hour);
    return item?.count || 0;
  }

  function getIntensity(count: number): string {
    if (count === 0) return "bg-muted";
    const ratio = count / maxCount;
    if (ratio < 0.25) return "bg-primary/20";
    if (ratio < 0.5) return "bg-primary/40";
    if (ratio < 0.75) return "bg-primary/60";
    return "bg-primary/90";
  }

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[600px]">
        <div className="flex gap-1">
          <div className="w-10" />
          {HOURS.filter((_, i) => i % 3 === 0).map((hour) => (
            <div
              key={hour}
              className="text-[10px] text-muted-foreground text-center"
              style={{ width: `${(3 / 24) * 100}%` }}
            >
              {hour.toString().padStart(2, "0")}:00
            </div>
          ))}
        </div>
        {DAYS.map((day, dayIndex) => (
          <div key={day} className="flex items-center gap-1 mb-1">
            <span className="text-[10px] text-muted-foreground w-10">{day}</span>
            <div className="flex-1 flex gap-[2px]">
              {HOURS.map((hour) => {
                const count = getCount(dayIndex, hour);
                return (
                  <div
                    key={hour}
                    className={cn(
                      "flex-1 h-6 rounded-sm transition-colors",
                      getIntensity(count)
                    )}
                    title={`${day} ${hour}:00 - ${count} posts`}
                  />
                );
              })}
            </div>
          </div>
        ))}
        <div className="flex items-center justify-end gap-2 mt-3">
          <span className="text-[10px] text-muted-foreground">Less</span>
          <div className="flex gap-[2px]">
            <div className="w-3 h-3 rounded-sm bg-muted" />
            <div className="w-3 h-3 rounded-sm bg-primary/20" />
            <div className="w-3 h-3 rounded-sm bg-primary/40" />
            <div className="w-3 h-3 rounded-sm bg-primary/60" />
            <div className="w-3 h-3 rounded-sm bg-primary/90" />
          </div>
          <span className="text-[10px] text-muted-foreground">More</span>
        </div>
      </div>
    </div>
  );
}
