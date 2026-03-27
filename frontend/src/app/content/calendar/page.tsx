"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { CalendarView } from "@/components/content/CalendarView";
import { api } from "@/lib/api";
import type { CalendarItem } from "@/types";

export default function ContentCalendarPage() {
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchCalendar() {
      try {
        const data = await api.get<CalendarItem[]>("/api/v1/content/calendar");
        setItems(data);
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }
    fetchCalendar();
  }, []);

  const handleReschedule = async (itemId: string, newDate: string) => {
    try {
      await api.patch(`/api/v1/calendar/${itemId}`, { scheduled_at: newDate });
      setItems((prev) =>
        prev.map((item) =>
          item.id === itemId ? { ...item, scheduled_at: newDate } : item
        )
      );
      toast.success("Content rescheduled");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to reschedule";
      toast.error(detail);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Content Calendar</h1>
        <p className="text-muted-foreground">Schedule and manage your content timeline</p>
      </div>

      {loading ? (
        <Skeleton className="h-[600px] w-full" />
      ) : items.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-lg font-medium text-muted-foreground">No scheduled content</p>
          <p className="text-sm text-muted-foreground mt-1">
            Content will appear here once you schedule posts from the Content Studio
          </p>
        </div>
      ) : (
        <CalendarView items={items} onReschedule={handleReschedule} />
      )}
    </div>
  );
}
