"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, LayoutGrid, List } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { KanbanBoard } from "@/components/content/KanbanBoard";
import { ContentCard } from "@/components/content/ContentCard";
import { api } from "@/lib/api";
import type { CalendarItem } from "@/types";

export default function ContentStudioPage() {
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"kanban" | "grid">("kanban");

  async function fetchItems(brandId?: string | null) {
    setLoading(true);
    try {
      const params: Record<string, string | number> = {};
      if (brandId) params.brand_id = brandId;
      const data = await api.get<CalendarItem[]>("/api/v1/content/calendar", params);
      setItems(data);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchItems();

    const handler = (e: Event) => {
      const brandId = (e as CustomEvent).detail?.brandId;
      fetchItems(brandId);
    };
    window.addEventListener("brand-changed", handler);
    return () => window.removeEventListener("brand-changed", handler);
  }, []);

  const handleStatusChange = async (itemId: string, newStatus: string) => {
    try {
      await api.patch(`/api/v1/calendar/${itemId}`, { status: newStatus });
      setItems((prev) =>
        prev.map((item) =>
          item.id === itemId ? { ...item, status: newStatus } : item
        )
      );
    } catch {
      // Handle error
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold">Content Studio</h1>
          <p className="text-muted-foreground">Create, manage, and schedule content</p>
        </div>
        <div className="flex gap-2">
          <div className="flex rounded-md border">
            <Button
              variant={view === "kanban" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("kanban")}
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
            <Button
              variant={view === "grid" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("grid")}
            >
              <List className="h-4 w-4" />
            </Button>
          </div>
          <Button>
            <Plus className="mr-2 h-4 w-4" />
            New Content
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-[500px] w-full" />
        </div>
      ) : view === "kanban" ? (
        <KanbanBoard items={items} onStatusChange={handleStatusChange} />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.length === 0 ? (
            <div className="col-span-full text-center py-12">
              <p className="text-lg font-medium text-muted-foreground">No content yet</p>
              <p className="text-sm text-muted-foreground mt-1">Create your first piece of content to get started</p>
            </div>
          ) : (
            items.map((item) => <ContentCard key={item.id} item={item} />)
          )}
        </div>
      )}
    </div>
  );
}
