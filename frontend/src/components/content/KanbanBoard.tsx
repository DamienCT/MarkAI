"use client";

import dynamic from "next/dynamic";
import type { CalendarItem } from "@/types";

// Read-only board: columns navigate to the stage list, items link to the
// detail page. Status changes happen there — the board never mutates status
// itself (the old drag-and-drop scaffolding was dead code and was removed).
export interface KanbanBoardProps {
  items: CalendarItem[];
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

export function KanbanBoard({ items }: KanbanBoardProps) {
  return <KanbanBoardInner items={items} />;
}
