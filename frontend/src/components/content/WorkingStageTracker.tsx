"use client";

import React, { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { CHANNEL_COLORS, CHANNEL_DISPLAY_NAMES } from "@/lib/constants";
import type { CalendarItem, ActiveAgentRun } from "@/types";

interface PipelineStep {
  key: string;
  label: string;
  short: string;
}

const CONTENT_PIPELINE_STEPS: readonly PipelineStep[] = [
  { key: "load_context", label: "Context", short: "Ctx" },
  { key: "enrich_user_brief", label: "Enrich", short: "Enr" },
  { key: "generate_hook", label: "Hook", short: "Hook" },
  { key: "generate_caption", label: "Caption", short: "Cap" },
  { key: "generate_hashtags", label: "Hashtags", short: "#" },
  { key: "source_product_image", label: "Product", short: "Prod" },
  { key: "generate_background", label: "Image", short: "Img" },
  { key: "apply_branding", label: "Branding", short: "Brand" },
  { key: "review_branding", label: "Review", short: "Rev" },
  { key: "adapt_platforms", label: "Adapt", short: "Adapt" },
  { key: "generate_mockups", label: "Mockups", short: "Mock" },
  { key: "store_content", label: "Save", short: "Save" },
];

// Video (reel) pipeline — keys MUST match VIDEO_PIPELINE_STEPS in
// agents/workflows/video/nodes.py (written to agent_runs current_step).
const VIDEO_PIPELINE_STEPS: readonly PipelineStep[] = [
  { key: "load_context", label: "Context", short: "Ctx" },
  { key: "enrich_user_brief", label: "Enrich", short: "Enr" },
  { key: "source_product_image", label: "Product", short: "Prod" },
  { key: "plan_shots", label: "Shot Plan", short: "Plan" },
  { key: "make_keyframe", label: "Keyframe", short: "Key" },
  { key: "render_video", label: "Render", short: "Rend" },
  { key: "store_video", label: "Save", short: "Save" },
];

function stepsForItemType(itemType?: string): readonly PipelineStep[] {
  return itemType === "reel" ? VIDEO_PIPELINE_STEPS : CONTENT_PIPELINE_STEPS;
}

function getStepIndex(
  stepKey?: string,
  steps: readonly PipelineStep[] = CONTENT_PIPELINE_STEPS
): number {
  if (!stepKey) return -1;
  const idx = steps.findIndex((s) => s.key === stepKey);
  return idx;
}

function timeAgo(dateString?: string): string {
  if (!dateString) return "";
  const started = new Date(dateString).getTime();
  const now = Date.now();
  const diffMs = now - started;
  if (diffMs < 0) return "just now";
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m ago`;
}

interface TrackedItem {
  calendarItem: CalendarItem;
  run: ActiveAgentRun;
  currentStepIndex: number;
}

/** Mini progress dots for use in Kanban cards */
export function PipelineProgressDots({
  currentStep,
  size = "sm",
  itemType,
}: {
  currentStep?: string;
  size?: "sm" | "xs";
  itemType?: string;
}) {
  const steps = stepsForItemType(itemType);
  const stepIdx = getStepIndex(currentStep, steps);
  const dotSize = size === "xs" ? "w-1.5 h-1.5" : "w-2 h-2";
  const gap = size === "xs" ? "gap-0.5" : "gap-1";

  return (
    <div className={`flex items-center ${gap}`}>
      {steps.map((step, i) => {
        let colorClass: string;
        if (i < stepIdx) {
          colorClass = "bg-indigo-500";
        } else if (i === stepIdx) {
          colorClass = "bg-indigo-400 animate-pulse";
        } else {
          colorClass = "bg-gray-300 dark:bg-gray-600";
        }
        return (
          <div
            key={step.key}
            className={`${dotSize} rounded-full ${colorClass}`}
            title={step.label}
          />
        );
      })}
    </div>
  );
}

interface WorkingStageTrackerProps {
  items: CalendarItem[];
  pollInterval?: number;
}

export function WorkingStageTracker({
  items,
  pollInterval = 5000,
}: WorkingStageTrackerProps) {
  const [activeRuns, setActiveRuns] = useState<ActiveAgentRun[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchActiveRuns = useCallback(async () => {
    try {
      // No agent_type filter — the tracker follows both content and video
      // (reel) runs; items are matched by calendar_item_id below.
      const runs = await api.get<ActiveAgentRun[]>("/api/v1/agents/runs/active");
      setActiveRuns(Array.isArray(runs) ? runs : []);
    } catch {
      // Silently fail — tracker is non-critical
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchActiveRuns();
    const interval = setInterval(fetchActiveRuns, pollInterval);
    return () => clearInterval(interval);
  }, [fetchActiveRuns, pollInterval]);

  // Match calendar items to their active runs
  const trackedItems: TrackedItem[] = items
    .map((item) => {
      const run = activeRuns.find(
        (r) => r.calendar_item_id === item.id
      );
      return {
        calendarItem: item,
        run: run || ({
          id: "",
          agent_type: "content",
          status: "running",
          created_at: "",
        } as ActiveAgentRun),
        currentStepIndex: run
          ? getStepIndex(run.current_step, stepsForItemType(item.item_type))
          : -1,
      };
    })
    .sort((a, b) => b.currentStepIndex - a.currentStepIndex);

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: Math.min(items.length, 3) }).map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  }

  if (trackedItems.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <div className="relative flex h-2.5 w-2.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-indigo-500" />
        </div>
        <h3 className="text-sm font-medium text-muted-foreground">
          Pipeline Progress
        </h3>
      </div>

      {trackedItems.map(({ calendarItem, run, currentStepIndex }) => {
        const steps = stepsForItemType(calendarItem.item_type);
        return (
        <Link
          key={calendarItem.id}
          href={`/content/${calendarItem.id}`}
          className="block"
        >
          <Card className="p-4 hover:shadow-md transition-shadow cursor-pointer border-indigo-200 dark:border-indigo-800">
            {/* Header: channel badge + title + brand */}
            <div className="flex items-start justify-between gap-2 mb-3">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <Badge
                  variant="outline"
                  className={`text-[10px] shrink-0 ${
                    CHANNEL_COLORS[calendarItem.channel] || ""
                  }`}
                >
                  {CHANNEL_DISPLAY_NAMES[calendarItem.channel] ||
                    calendarItem.channel}
                </Badge>
                <span className="text-sm font-medium truncate">
                  {calendarItem.title || "Untitled"}
                </span>
              </div>
              {calendarItem.brand_name && (
                <span className="text-[10px] text-muted-foreground shrink-0">
                  {calendarItem.brand_name}
                </span>
              )}
            </div>

            {/* Step progress bar */}
            <div className="mb-2">
              <div className="flex items-center gap-1">
                {steps.map((step, i) => {
                  const isCompleted = i < currentStepIndex;
                  const isCurrent = i === currentStepIndex;
                  const isPending = i > currentStepIndex;

                  return (
                    <React.Fragment key={step.key}>
                      {/* Dot */}
                      <div className="flex flex-col items-center" style={{ flex: "0 0 auto" }}>
                        <div
                          className={`w-3 h-3 rounded-full flex items-center justify-center transition-all ${
                            isCompleted
                              ? "bg-indigo-500"
                              : isCurrent
                              ? "bg-indigo-400 ring-2 ring-indigo-300 ring-offset-1 dark:ring-offset-gray-900"
                              : "bg-gray-200 dark:bg-gray-700"
                          }`}
                        >
                          {isCompleted && (
                            <svg
                              className="w-2 h-2 text-white"
                              fill="currentColor"
                              viewBox="0 0 20 20"
                            >
                              <path
                                fillRule="evenodd"
                                d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                                clipRule="evenodd"
                              />
                            </svg>
                          )}
                          {isCurrent && (
                            <div className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                          )}
                        </div>
                      </div>
                      {/* Connector line */}
                      {i < steps.length - 1 && (
                        <div
                          className={`h-0.5 flex-1 transition-colors ${
                            i < currentStepIndex
                              ? "bg-indigo-500"
                              : "bg-gray-200 dark:bg-gray-700"
                          }`}
                        />
                      )}
                    </React.Fragment>
                  );
                })}
              </div>

              {/* Step labels */}
              <div className="flex items-center mt-1.5">
                {steps.map((step, i) => {
                  const isCurrent = i === currentStepIndex;
                  return (
                    <React.Fragment key={step.key}>
                      <div
                        className="flex flex-col items-center"
                        style={{ flex: "0 0 auto", width: 12 }}
                      >
                        <span
                          className={`text-[8px] leading-none whitespace-nowrap ${
                            isCurrent
                              ? "text-indigo-600 dark:text-indigo-400 font-semibold"
                              : "text-muted-foreground"
                          }`}
                        >
                          {step.short}
                        </span>
                      </div>
                      {i < steps.length - 1 && (
                        <div className="flex-1" />
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>

            {/* Footer: current step name + time */}
            <div className="flex items-center justify-between mt-2 text-[11px] text-muted-foreground">
              <span>
                {currentStepIndex >= 0 ? (
                  <>
                    Step {currentStepIndex + 1}/{steps.length}
                    {" — "}
                    <span className="text-indigo-600 dark:text-indigo-400 font-medium">
                      {steps[currentStepIndex]?.label}
                    </span>
                  </>
                ) : (
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
                    Starting generation...
                  </span>
                )}
              </span>
              {run.started_at && (
                <span>Started {timeAgo(run.started_at)}</span>
              )}
            </div>
          </Card>
        </Link>
        );
      })}
    </div>
  );
}
