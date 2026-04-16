"use client";

import React, { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
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
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CHANNEL_COLORS } from "@/lib/constants";
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

function formatItemTime(item: CalendarItem): string {
  if (!item.scheduled_at) return "";
  const d = new Date(item.scheduled_at);
  const h = d.getHours();
  const m = d.getMinutes();
  if (h === 0 && m === 0) return "";
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// Color palette for brand-based color coding
const BRAND_COLORS = [
  "border-l-blue-400",
  "border-l-green-400",
  "border-l-purple-400",
  "border-l-orange-400",
  "border-l-pink-400",
  "border-l-cyan-400",
  "border-l-amber-400",
  "border-l-rose-400",
];

function getBrandColor(brandId: string): string {
  const hash = brandId.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  return BRAND_COLORS[hash % BRAND_COLORS.length];
}

interface CalendarViewProps {
  items: CalendarItem[];
  onReschedule?: (itemId: string, newDate: string) => Promise<void>;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// Ordered: Queued -> Working -> In Review -> Reworking -> Scheduled -> Published -> Failed
const STATUS_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  queued:      { bg: "bg-slate-200 dark:bg-slate-700",   text: "text-slate-800 dark:text-slate-200", label: "Queued" },
  working:     { bg: "bg-indigo-200 dark:bg-indigo-800", text: "text-indigo-900 dark:text-indigo-100", label: "Working" },
  in_review:   { bg: "bg-amber-200 dark:bg-amber-800",   text: "text-amber-900 dark:text-amber-100", label: "In Review" },
  reworking:   { bg: "bg-orange-200 dark:bg-orange-800",  text: "text-orange-900 dark:text-orange-100", label: "Reworking" },
  scheduled:   { bg: "bg-blue-200 dark:bg-blue-800",     text: "text-blue-900 dark:text-blue-100",   label: "Scheduled" },
  published:   { bg: "bg-green-200 dark:bg-green-800",    text: "text-green-900 dark:text-green-100", label: "Published" },
  failed:      { bg: "bg-red-200 dark:bg-red-800",        text: "text-red-900 dark:text-red-100",     label: "Failed" },
};

function getStatusStyle(status: string) {
  return STATUS_CONFIG[status] || STATUS_CONFIG.queued;
}

const MAX_VISIBLE_ITEMS = 4;

export function CalendarView({ items, onReschedule }: CalendarViewProps) {
  const router = useRouter();
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [dragItem, setDragItem] = useState<CalendarItem | null>(null);
  const [expandedDay, setExpandedDay] = useState<Date | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  const handleItemClick = useCallback((item: CalendarItem) => {
    router.push(`/content/${item.id}`);
  }, [router]);

  // Track viewport width for responsive layout
  React.useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < 768);
    }
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const monthStart = startOfMonth(currentMonth);
  const monthEnd = endOfMonth(currentMonth);
  const days = eachDayOfInterval({ start: monthStart, end: monthEnd });
  const startPadding = getDay(monthStart);
  // Fill remaining cells to complete the last row
  const totalCells = startPadding + days.length;
  const endPadding = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);

  // Pre-group items by date string for O(1) lookup per day
  const itemsByDateKey = useMemo(() => {
    const map: Record<string, CalendarItem[]> = {};
    for (const item of items) {
      if (!item.scheduled_at) continue;
      try {
        const key = format(parseISO(item.scheduled_at), "yyyy-MM-dd");
        if (!map[key]) map[key] = [];
        map[key].push(item);
      } catch {
        // skip invalid dates
      }
    }
    return map;
  }, [items]);

  function getItemsForDay(date: Date): CalendarItem[] {
    const key = format(date, "yyyy-MM-dd");
    return itemsByDateKey[key] || [];
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

  function renderItem(item: CalendarItem) {
    const style = getStatusStyle(item.status);
    const brandColor = getBrandColor(item.brand_id);
    return (
      <div
        key={item.id}
        draggable
        onDragStart={() => handleDragStart(item)}
        onClick={() => handleItemClick(item)}
        className={cn(
          "rounded-sm px-1.5 py-0.5 text-[10px] leading-tight cursor-pointer transition-opacity hover:opacity-80 border-l-2",
          style.bg,
          style.text,
          brandColor,
        )}
        title={`${item.brand_name ? `[${item.brand_name}] ` : ""}${item.title || "Untitled"} \u2014 ${style.label}${item.channel ? ` (${item.channel})` : ""}${item.pillar ? ` | Pillar: ${item.pillar}` : ""}${item.target_audience ? ` | Audience: ${item.target_audience}` : ""}`}
      >
        <div className="flex items-center gap-1">
          {item.channel && (
            <span className={cn(
              "inline-flex items-center rounded px-1 py-px text-[10px] font-bold uppercase shrink-0",
              CHANNEL_COLORS[item.channel] || "bg-gray-200 text-gray-700"
            )}>
              {CHANNEL_PREFIX[item.channel] || item.channel.slice(0, 2)}
            </span>
          )}
          {formatItemTime(item) && (
            <span className="text-[9px] opacity-50 shrink-0">{formatItemTime(item)}</span>
          )}
          <span className="truncate">{item.title || "Untitled"}</span>
        </div>
        {item.brand_name && (
          <div className="text-[10px] opacity-60 truncate">{item.brand_name}</div>
        )}
      </div>
    );
  }

  // Build sorted list of days-with-items for mobile list view
  const daysWithItems = useMemo(() => {
    const result: { date: Date; items: CalendarItem[] }[] = [];
    for (const day of days) {
      const key = format(day, "yyyy-MM-dd");
      const dayItems = itemsByDateKey[key] || [];
      if (dayItems.length > 0) {
        result.push({ date: day, items: dayItems });
      }
    }
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentMonth, itemsByDateKey]);

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

      {/* Mobile list view — shown below md breakpoint */}
      {isMobile && (
        <div className="space-y-4">
          {daysWithItems.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No content scheduled this month</p>
          ) : (
            daysWithItems.map(({ date, items: dayItems }) => (
              <div key={date.toISOString()}>
                <div className={cn(
                  "text-sm font-semibold mb-2 px-1",
                  isDateToday(date) && "text-primary"
                )}>
                  {format(date, "EEEE, MMM d")}
                  {isDateToday(date) && <span className="ml-2 text-xs font-normal text-primary">(Today)</span>}
                </div>
                <div className="space-y-1.5">
                  {dayItems.map((item) => {
                    const style = getStatusStyle(item.status);
                    const brandColor = getBrandColor(item.brand_id);
                    return (
                      <div
                        key={item.id}
                        onClick={() => handleItemClick(item)}
                        className={cn(
                          "rounded-md px-3 py-2 text-xs border-l-2 cursor-pointer hover:opacity-80 transition-opacity",
                          style.bg,
                          style.text,
                          brandColor,
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 truncate">
                            {item.channel && (
                              <span className={cn(
                                "inline-flex items-center rounded px-1 py-px text-[9px] font-bold uppercase shrink-0",
                                CHANNEL_COLORS[item.channel] || "bg-gray-200 text-gray-700"
                              )}>
                                {CHANNEL_PREFIX[item.channel] || item.channel.slice(0, 2)}
                              </span>
                            )}
                            {formatItemTime(item) && (
                              <span className="text-[10px] opacity-50 shrink-0">{formatItemTime(item)}</span>
                            )}
                            <span className="font-medium truncate">{item.title || "Untitled"}</span>
                          </div>
                          <span className="text-[10px] opacity-70 ml-2 shrink-0">{style.label}</span>
                        </div>
                        {item.brand_name && (
                          <div className="text-[10px] opacity-60 mt-0.5">{item.brand_name}</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Calendar Grid — hidden on mobile */}
      {!isMobile && <div className="grid grid-cols-7 gap-px bg-border rounded-lg overflow-hidden max-h-[700px] overflow-y-auto">
        {/* Weekday headers */}
        {WEEKDAYS.map((day) => (
          <div key={day} className="bg-muted p-2 text-center text-xs font-medium text-muted-foreground">
            {day}
          </div>
        ))}

        {/* Start padding */}
        {Array.from({ length: startPadding }).map((_, i) => (
          <div key={`pad-s-${i}`} className="bg-card/50 p-2 min-h-[80px] sm:min-h-[110px]" />
        ))}

        {/* Days */}
        {days.map((day) => {
          const dayItems = getItemsForDay(day);
          const isToday = isDateToday(day);
          const hasOverflow = dayItems.length > MAX_VISIBLE_ITEMS;

          return (
            <div
              key={day.toISOString()}
              className={cn(
                "bg-card p-1.5 min-h-[80px] sm:min-h-[110px] transition-colors",
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
                {dayItems.slice(0, MAX_VISIBLE_ITEMS).map((item) => renderItem(item))}
                {hasOverflow && (
                  <button
                    type="button"
                    className="text-[10px] text-muted-foreground px-1 hover:text-foreground hover:underline cursor-pointer w-full text-left"
                    onClick={() => setExpandedDay(day)}
                  >
                    +{dayItems.length - MAX_VISIBLE_ITEMS} more
                  </button>
                )}
              </div>
            </div>
          );
        })}

        {/* End padding */}
        {Array.from({ length: endPadding }).map((_, i) => (
          <div key={`pad-e-${i}`} className="bg-card/50 p-2 min-h-[80px] sm:min-h-[110px]" />
        ))}
      </div>}

      {/* Expanded day dialog overlay */}
      {expandedDay && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setExpandedDay(null)}
        >
          <div
            className="bg-card rounded-lg border shadow-lg p-4 w-full max-w-md max-h-[60vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">
                {format(expandedDay, "EEEE, MMMM d, yyyy")}
              </h3>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                onClick={() => setExpandedDay(null)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-1">
              {getItemsForDay(expandedDay).map((item) => {
                const style = getStatusStyle(item.status);
                const brandColor = getBrandColor(item.brand_id);
                return (
                  <div
                    key={item.id}
                    onClick={() => handleItemClick(item)}
                    className={cn(
                      "rounded-sm px-2 py-1.5 text-xs border-l-2 cursor-pointer hover:opacity-80 transition-opacity",
                      style.bg,
                      style.text,
                      brandColor,
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 truncate">
                        {item.channel && (
                          <span className={cn(
                            "inline-flex items-center rounded px-1 py-px text-[9px] font-bold uppercase shrink-0",
                            CHANNEL_COLORS[item.channel] || "bg-gray-200 text-gray-700"
                          )}>
                            {CHANNEL_PREFIX[item.channel] || item.channel.slice(0, 2)}
                          </span>
                        )}
                        {formatItemTime(item) && (
                          <span className="text-[10px] opacity-50 shrink-0">{formatItemTime(item)}</span>
                        )}
                        <span className="font-medium truncate">
                          {item.title || "Untitled"}
                        </span>
                      </div>
                      <span className="text-[10px] opacity-70 ml-2 shrink-0">{style.label}</span>
                    </div>
                    {item.brand_name && (
                      <div className="text-[10px] opacity-60 mt-0.5">{item.brand_name}</div>
                    )}
                    {(item.pillar || item.target_audience) && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {item.pillar && (
                          <span className="inline-flex items-center rounded px-1 py-px text-[9px] bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                            {item.pillar}
                          </span>
                        )}
                        {item.target_audience && (
                          <span className="inline-flex items-center rounded px-1 py-px text-[9px] bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300">
                            {item.target_audience}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
