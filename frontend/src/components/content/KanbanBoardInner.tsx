"use client";

import React, { useState, useMemo, useEffect, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useOpenedContent } from "@/lib/opened-content";
import type { CalendarItem, ActiveAgentRun } from "@/types";
import type { KanbanBoardProps } from "./KanbanBoard";
import { CHANNEL_COLORS } from "@/lib/constants";
import { PipelineProgressDots } from "./WorkingStageTracker";

const CHANNEL_PREFIX: Record<string, string> = {
  instagram: "IG", facebook: "FB", linkedin: "LI", youtube: "YT",
  tiktok: "TT", x: "X", website_blog: "BL", teams: "TM",
};

// Row 1: Content Pipeline (pre-publish)
const ROW1_COLUMNS: { id: string; label: string; color: string }[] = [
  { id: "planned", label: "Planned", color: "bg-slate-50 dark:bg-slate-900" },
  { id: "queued", label: "Queued", color: "bg-sky-50 dark:bg-sky-950" },
  { id: "working", label: "Working", color: "bg-indigo-50 dark:bg-indigo-950" },
  { id: "rendering", label: "Rendering", color: "bg-fuchsia-50 dark:bg-fuchsia-950" },
  { id: "in_review", label: "In Review", color: "bg-amber-50 dark:bg-amber-950" },
  { id: "reworking", label: "Reworking", color: "bg-orange-50 dark:bg-orange-950" },
];

// Row 2: Publishing Pipeline (approve → scheduled → published)
const ROW2_COLUMNS: { id: string; label: string; color: string }[] = [
  { id: "scheduled", label: "Scheduled", color: "bg-blue-50 dark:bg-blue-950" },
  { id: "published", label: "Published", color: "bg-green-50 dark:bg-green-950" },
  { id: "failed", label: "Failed", color: "bg-red-50 dark:bg-red-950" },
];

const COLUMNS = [...ROW1_COLUMNS, ...ROW2_COLUMNS];
const MAX_VISIBLE_ITEMS = 3;

/** Small green pill flagging a calendar item that hasn't been opened yet. */
function NewPill() {
  return (
    <span className="shrink-0 inline-flex items-center rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 leading-none">
      New
    </span>
  );
}

/** Compact single-line item shown in the column preview */
function CompactItem({
  item,
  currentStep,
  isNew,
}: {
  item: CalendarItem;
  currentStep?: string;
  isNew?: boolean;
}) {
  return (
    // Stop propagation so the click doesn't bubble to the column wrapper button
    // (which would otherwise navigate to the stage list instead of the post).
    <Link
      href={`/content/${item.id}`}
      className="block"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent/50 transition-colors group">
        <Badge variant="outline" className={`text-[10px] px-1 py-0 shrink-0 ${CHANNEL_COLORS[item.channel] || ""}`}>
          {CHANNEL_PREFIX[item.channel] || item.channel}
        </Badge>
        <span className="text-xs truncate flex-1 group-hover:text-primary transition-colors">
          {item.title || "Untitled"}
        </span>
        {isNew && <NewPill />}
        {currentStep && (
          <PipelineProgressDots currentStep={currentStep} size="xs" itemType={item.item_type} />
        )}
        {!currentStep && item.scheduled_at && (
          <span className="text-[10px] text-muted-foreground shrink-0">
            {new Date(item.scheduled_at).toLocaleDateString("en", { month: "short", day: "numeric" })}
            {" "}{new Date(item.scheduled_at).toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit", hour12: false })}
          </span>
        )}
      </div>
    </Link>
  );
}

export function KanbanBoardInner({ items }: KanbanBoardProps) {
  const [activeRuns, setActiveRuns] = useState<ActiveAgentRun[]>([]);
  const router = useRouter();
  const { isOpened } = useOpenedContent();

  // Fetch active runs for progress dots on working (content) and
  // rendering (video) items
  const hasWorkingItems = useMemo(
    () => items.some((i) => i.status === "working" || i.status === "rendering"),
    [items]
  );

  const fetchActiveRuns = useCallback(async () => {
    if (!hasWorkingItems) return;
    try {
      // No agent_type filter — covers both content and video (reel) runs;
      // items are matched by calendar_item_id.
      const runs = await api.get<ActiveAgentRun[]>("/api/v1/agents/runs/active");
      setActiveRuns(Array.isArray(runs) ? runs : []);
    } catch {
      // Non-critical
    }
  }, [hasWorkingItems]);

  useEffect(() => {
    // Defer the initial fetch to a macrotask so no setState fires
    // synchronously inside the effect body (avoids cascading renders).
    const initial = setTimeout(fetchActiveRuns, 0);
    if (!hasWorkingItems) return () => clearTimeout(initial);
    const interval = setInterval(fetchActiveRuns, 5000);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
    };
  }, [fetchActiveRuns, hasWorkingItems]);

  // Map calendar_item_id -> current_step for quick lookup
  const runStepMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const run of activeRuns) {
      if (run.calendar_item_id && run.current_step) {
        map[run.calendar_item_id] = run.current_step;
      }
    }
    return map;
  }, [activeRuns]);

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
        <button
          type="button"
          onClick={() => columnItems.length > 0 && router.push(`/content/stage/${column.id}`)}
          className={`w-full text-left rounded-lg border border-dashed p-2 min-h-[180px] flex flex-col transition-colors ${column.color} ${
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
                  <CompactItem
                    key={item.id}
                    item={item}
                    currentStep={column.id === "working" || column.id === "rendering" ? runStepMap[item.id] : undefined}
                    isNew={!isOpened(item.id)}
                  />
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
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 w-full">
      {/* Row 1: Content Pipeline */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Content Pipeline</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-2">
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
  );
}
