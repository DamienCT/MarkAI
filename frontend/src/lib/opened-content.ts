/**
 * Tracks which calendar items the user has already opened in Content Studio.
 *
 * Backed by localStorage so the "New" badge persists across reloads but stays
 * per-browser (no backend table, no per-user sync). Capped at MAX_TRACKED ids
 * so the list never grows unbounded — the oldest entries fall off first.
 */
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "markai.opened_content_ids";
const MAX_TRACKED = 500;
const SYNC_EVENT = "markai.opened-content-changed";

function readFromStorage(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeToStorage(ids: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
    // Notify other components in the same tab — 'storage' only fires cross-tab.
    window.dispatchEvent(new CustomEvent(SYNC_EVENT));
  } catch {
    // Quota exceeded or storage disabled — silently ignore.
  }
}

export function useOpenedContent() {
  const [openedIds, setOpenedIds] = useState<Set<string>>(() => new Set(readFromStorage()));

  useEffect(() => {
    if (typeof window === "undefined") return;
    const refresh = () => setOpenedIds(new Set(readFromStorage()));
    window.addEventListener(SYNC_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(SYNC_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const markOpened = useCallback((id: string) => {
    if (!id) return;
    const current = readFromStorage();
    if (current.includes(id)) return; // already tracked — keep order, skip write
    const next = [...current, id].slice(-MAX_TRACKED);
    writeToStorage(next);
    setOpenedIds(new Set(next));
  }, []);

  const isOpened = useCallback(
    (id: string) => openedIds.has(id),
    [openedIds]
  );

  return { openedIds, markOpened, isOpened };
}
