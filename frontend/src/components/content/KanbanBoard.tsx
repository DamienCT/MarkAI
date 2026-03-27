"use client";

import React, { useState } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/lib/utils";
import type { CalendarItem, Channel } from "@/types";

const CHANNEL_DISPLAY_NAMES: Record<string, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  youtube: "YouTube",
  tiktok: "TikTok",
  x: "X (Twitter)",
  website_blog: "Blog",
  teams: "Teams",
};

// Row 1: Content Pipeline (pre-publish)
const ROW1_COLUMNS: { id: string; label: string; color: string }[] = [
  { id: "queued", label: "Queued", color: "bg-slate-50 dark:bg-slate-900" },
  { id: "working", label: "Working", color: "bg-indigo-50 dark:bg-indigo-950" },
  { id: "in_review", label: "In Review", color: "bg-amber-50 dark:bg-amber-950" },
  { id: "reworking", label: "Reworking", color: "bg-orange-50 dark:bg-orange-950" },
];

// Row 2: Publishing Pipeline (post-approve)
const ROW2_COLUMNS: { id: string; label: string; color: string }[] = [
  { id: "approved", label: "Approved", color: "bg-cyan-50 dark:bg-cyan-950" },
  { id: "scheduled", label: "Scheduled", color: "bg-blue-50 dark:bg-blue-950" },
  { id: "published", label: "Published", color: "bg-green-50 dark:bg-green-950" },
  { id: "failed", label: "Failed", color: "bg-red-50 dark:bg-red-950" },
];

const COLUMNS = [...ROW1_COLUMNS, ...ROW2_COLUMNS];

interface KanbanBoardProps {
  items: CalendarItem[];
  onStatusChange: (itemId: string, newStatus: string) => Promise<void>;
}

function SortableItem({ item }: { item: CalendarItem }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id,
    data: { status: item.status },
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <KanbanCard item={item} />
    </div>
  );
}

function KanbanCard({ item }: { item: CalendarItem }) {
  return (
    <Link href={`/content/${item.id}`}>
      <Card className="p-3 cursor-pointer hover:shadow-md transition-shadow">
        <p className="text-sm font-medium line-clamp-2">{item.title || "Untitled"}</p>
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          {item.channel && (
            <Badge variant="outline" className="text-[10px]">
              {CHANNEL_DISPLAY_NAMES[item.channel] || item.channel}
            </Badge>
          )}
          {item.priority != null && item.priority > 0 && (
            <Badge variant="secondary" className="text-[10px]">
              P{item.priority}
            </Badge>
          )}
        </div>
        {item.scheduled_at && (
          <p className="text-[10px] text-muted-foreground mt-2">
            {formatDate(item.scheduled_at)}
          </p>
        )}
      </Card>
    </Link>
  );
}

export function KanbanBoard({ items, onStatusChange }: KanbanBoardProps) {
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor)
  );

  const activeItem = items.find((c) => c.id === activeId);

  function handleDragStart(event: DragStartEvent) {
    setActiveId(event.active.id as string);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    setActiveId(null);

    if (!over) return;

    const draggedItem = items.find((c) => c.id === active.id);
    if (!draggedItem) return;

    const overId = over.id as string;
    const targetColumn = COLUMNS.find((col) => col.id === overId);

    if (targetColumn && draggedItem.status !== targetColumn.id) {
      onStatusChange(draggedItem.id, targetColumn.id);
    } else {
      const overItem = items.find((c) => c.id === overId);
      if (overItem && draggedItem.status !== overItem.status) {
        onStatusChange(draggedItem.id, overItem.status);
      }
    }
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="space-y-6 w-full">
        {/* Row 1: Content Pipeline */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">Content Pipeline</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {ROW1_COLUMNS.map((column) => {
              const columnItems = items.filter((c) => c.status === column.id);
              return (
                <div key={column.id} className="min-w-0">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-medium truncate">{column.label}</h3>
                    <Badge variant="secondary" className="text-xs ml-1 shrink-0">
                      {columnItems.length}
                    </Badge>
                  </div>
                  <div className={`space-y-2 min-h-[200px] rounded-lg border border-dashed p-2 ${column.color}`}>
                    <SortableContext
                      items={columnItems.map((c) => c.id)}
                      strategy={verticalListSortingStrategy}
                      id={column.id}
                    >
                      {columnItems.length === 0 ? (
                        <div className="flex items-center justify-center h-24 text-xs text-muted-foreground">
                          No items
                        </div>
                      ) : (
                        columnItems.map((item) => (
                          <SortableItem key={item.id} item={item} />
                        ))
                      )}
                    </SortableContext>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="border-t border-border" />

        {/* Row 2: Publishing Pipeline */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">Publishing Pipeline</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {ROW2_COLUMNS.map((column) => {
              const columnItems = items.filter((c) => c.status === column.id);
              return (
                <div key={column.id} className="min-w-0">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-medium truncate">{column.label}</h3>
                    <Badge variant="secondary" className="text-xs ml-1 shrink-0">
                      {columnItems.length}
                    </Badge>
                  </div>
                  <div className={`space-y-2 min-h-[200px] rounded-lg border border-dashed p-2 ${column.color}`}>
                    <SortableContext
                      items={columnItems.map((c) => c.id)}
                      strategy={verticalListSortingStrategy}
                      id={column.id}
                    >
                      {columnItems.length === 0 ? (
                        <div className="flex items-center justify-center h-24 text-xs text-muted-foreground">
                          No items
                        </div>
                      ) : (
                        columnItems.map((item) => (
                          <SortableItem key={item.id} item={item} />
                        ))
                      )}
                    </SortableContext>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <DragOverlay>
        {activeItem ? <KanbanCard item={activeItem} /> : null}
      </DragOverlay>
    </DndContext>
  );
}
