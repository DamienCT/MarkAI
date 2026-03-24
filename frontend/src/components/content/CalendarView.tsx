"use client";

import React, { useState } from "react";
import {
  format,
  startOfMonth,
  endOfMonth,
  eachDayOfInterval,
  isSameMonth,
  isSameDay,
  addMonths,
  subMonths,
  getDay,
  parseISO,
  isToday as isDateToday,
} from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CalendarItem } from "@/types";

const CHANNEL_PREFIX: Record<string, string> = {
  instagram: "IG",
  facebook: "FB",
  linkedin: "LI",
  youtube: "YT",
  tiktok: "TT",
  x: "X",
  website_blog: "BL",
  teams: "TM",
};

interface CalendarViewProps {
  items: CalendarItem[];
  onReschedule?: (itemId: string, newDate: string) => Promise<void>;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// Ordered: Queued → Working → In Review → Reworking → Approved → Scheduled → Published → Failed
const STATUS_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  queued:      { bg: "bg-slate-200 dark:bg-slate-700",   text: "text-slate-800 dark:text-slate-200", label: "Queued" },
  working:     { bg: "bg-indigo-200 dark:bg-indigo-800", text: "text-indigo-900 dark:text-indigo-100", label: "Working" },
  in_review:   { bg: "bg-amber-200 dark:bg-amber-800",   text: "text-amber-900 dark:text-amber-100", label: "In Review" },
  reworking:   { bg: "bg-orange-200 dark:bg-orange-800",  text: "text-orange-900 dark:text-orange-100", label: "Reworking" },
  approved:    { bg: "bg-cyan-200 dark:bg-cyan-800",      text: "text-cyan-900 dark:text-cyan-100",   label: "Approved" },
  scheduled:   { bg: "bg-blue-200 dark:bg-blue-800",     text: "text-blue-900 dark:text-blue-100",   label: "Scheduled" },
  published:   { bg: "bg-green-200 dark:bg-green-800",    text: "text-green-900 dark:text-green-100", label: "Published" },
  failed:      { bg: "bg-red-200 dark:bg-red-800",        text: "text-red-900 dark:text-red-100",     label: "Failed" },
};

function getStatusStyle(status: string) {
  return STATUS_CONFIG[status] || STATUS_CONFIG.queued;
}

export function CalendarView({ items, onReschedule }: CalendarViewProps) {
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [dragItem, setDragItem] = useState<CalendarItem | null>(null);

  const monthStart = startOfMonth(currentMonth);
  const monthEnd = endOfMonth(currentMonth);
  const days = eachDayOfInterval({ start: monthStart, end: monthEnd });
  const startPadding = getDay(monthStart);
  // Fill remaining cells to complete the last row
  const totalCells = startPadding + days.length;
  const endPadding = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);

  function getItemsForDay(date: Date): CalendarItem[] {
    return items.filter((item) => {
      if (!item.scheduled_at) return false;
      try {
        return isSameDay(parseISO(item.scheduled_at), date);
      } catch {
        return false;
      }
    });
  }

  function handleDragStart(item: CalendarItem) {
    setDragItem(item);
  }

  function handleDrop(date: Date) {
    if (dragItem && onReschedule) {
      onReschedule(dragItem.id, date.toISOString());
    }
    setDragItem(null);
  }

  const today = new Date();

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <Button variant="outline" size="sm" onClick={() => setCurrentMonth(subMonths(currentMonth, 1))}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <h2 className="text-lg font-semibold">{format(currentMonth, "MMMM yyyy")}</h2>
        <Button variant="outline" size="sm" onClick={() => setCurrentMonth(addMonths(currentMonth, 1))}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-xs">
        {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
          <div key={key} className="flex items-center gap-1.5">
            <div className={cn("w-3 h-3 rounded-sm", cfg.bg)} />
            <span className="text-muted-foreground">{cfg.label}</span>
          </div>
        ))}
      </div>

      {/* Calendar Grid */}
      <div className="grid grid-cols-7 gap-px bg-border rounded-lg overflow-hidden">
        {/* Weekday headers */}
        {WEEKDAYS.map((day) => (
          <div key={day} className="bg-muted p-2 text-center text-xs font-medium text-muted-foreground">
            {day}
          </div>
        ))}

        {/* Start padding */}
        {Array.from({ length: startPadding }).map((_, i) => (
          <div key={`pad-s-${i}`} className="bg-card/50 p-2 min-h-[110px]" />
        ))}

        {/* Days */}
        {days.map((day) => {
          const dayItems = getItemsForDay(day);
          const isToday = isDateToday(day);

          return (
            <div
              key={day.toISOString()}
              className={cn(
                "bg-card p-1.5 min-h-[110px] transition-colors",
                isToday && "ring-2 ring-primary ring-inset",
                dragItem && "hover:bg-accent/50"
              )}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => handleDrop(day)}
            >
              <p
                className={cn(
                  "text-xs font-medium mb-1 px-1",
                  isToday && "text-primary font-bold",
                  !isSameMonth(day, currentMonth) && "text-muted-foreground"
                )}
              >
                {format(day, "d")}
              </p>
              <div className="space-y-0.5">
                {dayItems.slice(0, 4).map((item) => {
                  const style = getStatusStyle(item.status);
                  return (
                    <div
                      key={item.id}
                      draggable
                      onDragStart={() => handleDragStart(item)}
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] leading-tight truncate cursor-move transition-opacity hover:opacity-80",
                        style.bg,
                        style.text
                      )}
                      title={`${item.title || "Untitled"} — ${style.label}${item.channel ? ` (${item.channel})` : ""}`}
                    >
                      {item.channel && (
                        <span className="font-semibold uppercase">{CHANNEL_PREFIX[item.channel] || item.channel.slice(0, 2)} </span>
                      )}
                      {item.title || "Untitled"}
                    </div>
                  );
                })}
                {dayItems.length > 4 && (
                  <p className="text-[10px] text-muted-foreground px-1">+{dayItems.length - 4} more</p>
                )}
              </div>
            </div>
          );
        })}

        {/* End padding */}
        {Array.from({ length: endPadding }).map((_, i) => (
          <div key={`pad-e-${i}`} className="bg-card/50 p-2 min-h-[110px]" />
        ))}
      </div>
    </div>
  );
}
