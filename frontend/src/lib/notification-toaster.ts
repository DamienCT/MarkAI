"use client";

/**
 * Listens for the bell's 30s notification poll and pops a toast on every
 * NEW notification (never seen before by this browser). Skips a
 * content_ready notif when post-watch already toasted it locally (5s path).
 */
import { useEffect } from "react";
import { toast } from "sonner";
import { wasPostRecentlyToasted } from "@/lib/post-watch";

/** Field shape the backend actually returns from /api/v1/notifications.
 * (The exported `Notification` type in @/types is stale — uses message/type
 * instead of body/notification_type.) */
interface BellNotification {
  id: string;
  notification_type: string;
  title: string;
  body: string | null;
  reference_type: string | null;
  reference_id: string | null;
  is_read: boolean;
  created_at: string;
}

export const NOTIFICATIONS_FETCHED_EVENT = "markai.notifications-fetched";

const SEEN_KEY = "markai.toasted_notification_ids";
const MAX_TRACKED = 200;
const POSITIVE_TYPES = new Set([
  "content_ready",
  "context_ready",
  "context_all_ready",
]);

function readSeen(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(SEEN_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? new Set(parsed.filter((x): x is string => typeof x === "string"))
      : new Set();
  } catch {
    return new Set();
  }
}

function writeSeen(ids: Set<string>) {
  if (typeof window === "undefined") return;
  try {
    // Keep only the most recent MAX_TRACKED ids (Set preserves insertion order
    // since ES2015 — we trim from the front).
    const list = Array.from(ids);
    const trimmed = list.length > MAX_TRACKED ? list.slice(-MAX_TRACKED) : list;
    window.localStorage.setItem(SEEN_KEY, JSON.stringify(trimmed));
  } catch {
    /* quota / disabled */
  }
}

/** Mount this hook ONCE at app level. */
export function useNotificationToaster(): void {
  useEffect(() => {
    // On first mount, prime the seen set with whatever's already in the bell
    // (so we don't pop 5 toasts for old unread notifs sitting in the DB).
    let primed = false;

    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const list = (detail?.notifications || []) as BellNotification[];
      if (!Array.isArray(list)) return;

      const seen = readSeen();

      if (!primed) {
        // First payload after refresh — assume the user has already noticed
        // anything in there via the bell. Just record their ids and bail.
        for (const n of list) {
          if (n?.id) seen.add(n.id);
        }
        writeSeen(seen);
        primed = true;
        return;
      }

      let changed = false;
      for (const n of list) {
        if (!n?.id || seen.has(n.id)) continue;

        // Dedup vs post-watch (Option A): if a freshly-created post was
        // already toasted via the 5s polling path, mark this notif seen
        // and skip its own toast.
        if (
          n.notification_type === "content_ready" &&
          n.reference_id &&
          wasPostRecentlyToasted(n.reference_id)
        ) {
          seen.add(n.id);
          changed = true;
          continue;
        }

        const fn = POSITIVE_TYPES.has(n.notification_type)
          ? toast.success
          : toast.info;
        fn(n.title || "New notification", {
          description: n.body || undefined,
          duration: 6000,
        });

        seen.add(n.id);
        changed = true;
      }

      if (changed) writeSeen(seen);
    };

    window.addEventListener(NOTIFICATIONS_FETCHED_EVENT, handler);
    return () => {
      window.removeEventListener(NOTIFICATIONS_FETCHED_EVENT, handler);
    };
  }, []);
}
