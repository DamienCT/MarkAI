"use client";

import dynamic from "next/dynamic";
import type { CalendarItem } from "@/types";

export interface KanbanBoardProps {
  items: CalendarItem[];
  onStatusChange: (itemId: string, newStatus: string) => Promise<void>;
}

const KanbanBoardInner = dynamic(
  () => import("./KanbanBoardInner").then((mod) => mod.KanbanBoardInner),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        Loading board...
      </div>
    ),
  }
);

export function KanbanBoard({ items, onStatusChange }: KanbanBoardProps) {
  return <KanbanBoardInner items={items} onStatusChange={onStatusChange} />;
}
