"use client";

/**
 * Tracks newly-created posts so we can pop a green toast as soon as their
 * workflow finishes (status flips to `in_review`). Polling lives globally
 * via usePostWatchToaster() so the toast fires even if the user navigated
 * away from Content Studio. State is persisted in localStorage so it
 * survives reloads and syncs across tabs.
 *
 * Dedup with notification-toaster.ts: when we pop a toast we mark the
 * content_id as "recently toasted" so the bell-level toaster skips the
 * same event (notifications.reference_id == content_id).
 */
import { useEffect } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { CHANNEL_DISPLAY_NAMES } from "@/types";
import type { CalendarItem, Channel } from "@/types";

const WATCHED_KEY = "markai.watched_posts";
const TOASTED_KEY = "markai.toasted_post_ids";
const WATCHED_SYNC_EVENT = "markai.watched-posts-changed";
const MAX_WATCH_MS = 10 * 60 * 1000;
const TOASTED_TTL_MS = 15 * 60 * 1000;
const POLL_INTERVAL_MS = 5000;

interface WatchedPost {
  id: string;
  title: string;
  channel: string;
  createdAt: number;
}

function readWatched(): WatchedPost[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(WATCHED_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (x): x is WatchedPost =>
        x &&
        typeof x.id === "string" &&
        typeof x.title === "string" &&
        typeof x.channel === "string" &&
        typeof x.createdAt === "number"
    );
  } catch {
    return [];
  }
}

function writeWatched(items: WatchedPost[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(WATCHED_KEY, JSON.stringify(items));
    window.dispatchEvent(new CustomEvent(WATCHED_SYNC_EVENT));
  } catch {
    /* quota / disabled */
  }
}

function readToasted(): Record<string, number> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(TOASTED_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const now = Date.now();
    const cleaned: Record<string, number> = {};
    for (const [id, ts] of Object.entries(parsed)) {
      if (typeof ts === "number" && now - ts <= TOASTED_TTL_MS) {
        cleaned[id] = ts;
      }
    }
    return cleaned;
  } catch {
    return {};
  }
}

function writeToasted(map: Record<string, number>) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOASTED_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

/** Begin watching a freshly-created post for completion. */
export function watchPost(id: string, title: string, channel: string): void {
  if (!id) return;
  const current = readWatched();
  if (current.some((w) => w.id === id)) return;
  writeWatched([
    ...current,
    { id, title, channel, createdAt: Date.now() },
  ]);
}

/** True when a content_id was toasted recently by post-watch — used by
 * notification-toaster to avoid double-toasting the same completion event. */
export function wasPostRecentlyToasted(contentId: string): boolean {
  if (!contentId) return false;
  const map = readToasted();
  const ts = map[contentId];
  return typeof ts === "number" && Date.now() - ts <= TOASTED_TTL_MS;
}

function markToasted(contentId: string) {
  const map = readToasted();
  map[contentId] = Date.now();
  writeToasted(map);
}

/** Mount this hook ONCE at app level. Polls every 5s and toasts on done. */
export function usePostWatchToaster(): void {
  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      if (cancelled) return;
      const now = Date.now();
      const current = readWatched();
      if (current.length === 0) return;

      // Drop expired before polling
      const fresh = current.filter((w) => now - w.createdAt <= MAX_WATCH_MS);
      if (fresh.length !== current.length) {
        writeWatched(fresh);
      }
      if (fresh.length === 0) return;

      await Promise.all(
        fresh.map(async (w) => {
          try {
            const item = await api.get<CalendarItem>(
              `/api/v1/calendar/${w.id}`
            );
            if (item.status === "in_review") {
              const label =
                CHANNEL_DISPLAY_NAMES[w.channel as Channel] || w.channel;
              toast.success(`${label} post ready — "${w.title}"`, {
                duration: 8000,
              });
              writeWatched(readWatched().filter((x) => x.id !== w.id));
              markToasted(w.id);
            }
          } catch {
            /* item deleted / auth lost — skip */
          }
        })
      );
    };

    const interval = setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);
}
