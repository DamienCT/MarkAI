"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { CalendarView } from "@/components/content/CalendarView";
import { api } from "@/lib/api";
import type { CalendarItem } from "@/types";

export default function ContentCalendarPage() {
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchCalendar() {
      try {
        const data = await api.get<CalendarItem[]>("/api/v1/calendar");
        setItems(Array.isArray(data) ? data : []);
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
          <Button variant="outline" className="mt-4" asChild>
            <Link href="/content">Go to Content Studio</Link>
          </Button>
        </div>
      ) : (
        <CalendarView items={items} onReschedule={handleReschedule} />
      )}
    </div>
  );
}
