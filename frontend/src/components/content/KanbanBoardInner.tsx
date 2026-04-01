"use client";

import React, { useState, useMemo } from "react";
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
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/lib/utils";
import type { CalendarItem } from "@/types";
import type { KanbanBoardProps } from "./KanbanBoard";

const CHANNEL_PREFIX: Record<string, string> = {
  instagram: "IG", facebook: "FB", linkedin: "LI", youtube: "YT",
  tiktok: "TT", x: "X", website_blog: "BL", teams: "TM",
};

const CHANNEL_COLORS: Record<string, string> = {
  instagram: "bg-pink-100 text-pink-700 dark:bg-pink-900 dark:text-pink-300",
  facebook: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  linkedin: "bg-sky-100 text-sky-700 dark:bg-sky-900 dark:text-sky-300",
  youtube: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
  tiktok: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  x: "bg-zinc-100 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-300",
  website_blog: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  teams: "bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300",
};

const CHANNEL_DISPLAY_NAMES: Record<string, string> = {
  instagram: "Instagram", facebook: "Facebook", linkedin: "LinkedIn",
  youtube: "YouTube", tiktok: "TikTok", x: "X (Twitter)",
  website_blog: "Blog", teams: "Teams",
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
  { id: "publishing", label: "Publishing", color: "bg-violet-50 dark:bg-violet-950" },
  { id: "published", label: "Published", color: "bg-green-50 dark:bg-green-950" },
  { id: "failed", label: "Failed", color: "bg-red-50 dark:bg-red-950" },
];

const COLUMNS = [...ROW1_COLUMNS, ...ROW2_COLUMNS];
const MAX_VISIBLE_ITEMS = 3;

/** Compact single-line item shown in the column preview */
function CompactItem({ item }: { item: CalendarItem }) {
  return (
    <Link href={`/content/${item.id}`} className="block">
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent/50 transition-colors group">
        <Badge variant="outline" className={`text-[9px] px-1 py-0 shrink-0 ${CHANNEL_COLORS[item.channel] || ""}`}>
          {CHANNEL_PREFIX[item.channel] || item.channel}
        </Badge>
        <span className="text-xs truncate flex-1 group-hover:text-primary transition-colors">
          {item.title || "Untitled"}
        </span>
        {item.scheduled_at && (
          <span className="text-[9px] text-muted-foreground shrink-0">
            {new Date(item.scheduled_at).toLocaleDateString("en", { month: "short", day: "numeric" })}
          </span>
        )}
      </div>
    </Link>
  );
}

/** Full card shown in the stage modal and drag overlay */
function KanbanCard({ item }: { item: CalendarItem }) {
  return (
    <Link href={`/content/${item.id}`}>
      <Card className="p-3 cursor-pointer hover:shadow-md transition-shadow">
        <p className="text-sm font-medium line-clamp-2">{item.title || "Untitled"}</p>
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          {item.channel && (
            <Badge variant="outline" className={`text-[10px] ${CHANNEL_COLORS[item.channel] || ""}`}>
              {CHANNEL_DISPLAY_NAMES[item.channel] || item.channel}
            </Badge>
          )}
          {item.pillar && (
            <Badge variant="secondary" className="text-[10px] bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300">
              {item.pillar}
            </Badge>
          )}
          {item.target_audience && (
            <Badge variant="secondary" className="text-[10px] bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-300">
              {item.target_audience}
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

export function KanbanBoardInner({ items, onStatusChange }: KanbanBoardProps) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const router = useRouter();

  const itemsByStatus = useMemo(() => {
    const map: Record<string, CalendarItem[]> = {};
    for (const col of COLUMNS) {
      map[col.id] = [];
    }
    for (const item of items) {
      if (map[item.status]) {
        map[item.status].push(item);
      }
    }
    return map;
  }, [items]);

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

  function renderColumn(column: { id: string; label: string; color: string }) {
    const columnItems = itemsByStatus[column.id] || [];
    const visibleItems = columnItems.slice(0, MAX_VISIBLE_ITEMS);
    const hiddenCount = columnItems.length - visibleItems.length;

    return (
      <div key={column.id} className="min-w-0">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-medium truncate">{column.label}</h3>
          <Badge variant="secondary" className="text-[10px] ml-1 shrink-0 tabular-nums">
            {columnItems.length}
          </Badge>
        </div>
        <SortableContext
          items={columnItems.map((c) => c.id)}
          strategy={verticalListSortingStrategy}
          id={column.id}
        >
          <button
            type="button"
            onClick={() => columnItems.length > 0 && router.push(`/content/stage/${column.id}`)}
            className={`w-full text-left rounded-lg border border-dashed p-2 h-[180px] flex flex-col transition-colors ${column.color} ${
              columnItems.length > 0 ? "cursor-pointer hover:border-primary/50" : "cursor-default"
            }`}
          >
            {columnItems.length === 0 ? (
              <div className="flex items-center justify-center flex-1 text-xs text-muted-foreground">
                No items
              </div>
            ) : (
              <>
                <div className="flex-1 overflow-hidden space-y-0.5">
                  {visibleItems.map((item) => (
                    <CompactItem key={item.id} item={item} />
                  ))}
                </div>
                {hiddenCount > 0 && (
                  <div className="text-center pt-1 border-t border-dashed mt-1">
                    <span className="text-[10px] text-primary font-medium">
                      +{hiddenCount} more — click to view all
                    </span>
                  </div>
                )}
              </>
            )}
          </button>
        </SortableContext>
      </div>
    );
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="flex flex-col gap-4 w-full">
        {/* Row 1: Content Pipeline */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Content Pipeline</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {ROW1_COLUMNS.map(renderColumn)}
          </div>
        </div>

        <div className="border-t border-border" />

        {/* Row 2: Publishing Pipeline */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Publishing Pipeline</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
            {ROW2_COLUMNS.map(renderColumn)}
          </div>
        </div>
      </div>

      <DragOverlay>
        {activeItem ? <KanbanCard item={activeItem} /> : null}
      </DragOverlay>

    </DndContext>
  );
}
