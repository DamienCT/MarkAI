"use client";

import React from "react";
import { cn } from "@/lib/utils";
import type { QueueInfo } from "@/types";

interface QueueDepthProps {
  queues: QueueInfo[];
}

export function QueueDepth({ queues }: QueueDepthProps) {
  if (queues.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        No queue data available
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {queues.map((queue) => {
        const total = queue.pending + queue.processing + queue.completed + queue.failed;
        const pendingPct = total > 0 ? (queue.pending / total) * 100 : 0;
        const processingPct = total > 0 ? (queue.processing / total) * 100 : 0;
        const completedPct = total > 0 ? (queue.completed / total) * 100 : 0;
        const failedPct = total > 0 ? (queue.failed / total) * 100 : 0;

        return (
          <div key={queue.name} className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">{queue.name}</p>
              <p className="text-xs text-muted-foreground">Total: {total}</p>
            </div>
            <div className="flex h-3 rounded-full overflow-hidden bg-muted">
              {completedPct > 0 && (
                <div
                  className="bg-green-500 transition-all"
                  style={{ width: `${completedPct}%` }}
                  title={`Completed: ${queue.completed}`}
                />
              )}
              {processingPct > 0 && (
                <div
                  className="bg-blue-500 transition-all"
                  style={{ width: `${processingPct}%` }}
                  title={`Processing: ${queue.processing}`}
                />
              )}
              {pendingPct > 0 && (
                <div
                  className="bg-amber-500 transition-all"
                  style={{ width: `${pendingPct}%` }}
                  title={`Pending: ${queue.pending}`}
                />
              )}
              {failedPct > 0 && (
                <div
                  className="bg-red-500 transition-all"
                  style={{ width: `${failedPct}%` }}
                  title={`Failed: ${queue.failed}`}
                />
              )}
            </div>
            <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-amber-500" /> Pending: {queue.pending}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-blue-500" /> Processing: {queue.processing}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-green-500" /> Done: {queue.completed}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-red-500" /> Failed: {queue.failed}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
