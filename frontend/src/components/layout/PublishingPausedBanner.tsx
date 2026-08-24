"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { PauseCircle } from "lucide-react";

/** Slim app-wide banner shown while the global publishing kill switch is
 *  engaged, so editors know why approved/scheduled content is not going
 *  out. Reads the role-agnostic /publishing-status endpoint (boolean only);
 *  admins get a link to the controls on the System page.
 *
 *  Best-effort: any fetch failure renders nothing rather than a wrong
 *  banner — the enforcement itself lives in the backend. */
export function PublishingPausedBanner() {
  const { data: session } = useSession();
  // null = unknown (loading or fetch failed) → render nothing.
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const status = await api.get<{ enabled: boolean }>(
          "/api/v1/system/publishing-status"
        );
        if (!cancelled) setEnabled(status.enabled);
      } catch {
        if (!cancelled) setEnabled(null);
      }
    };

    check();
    // Re-check when the tab regains focus — an admin may have flipped the
    // switch in another tab, and polling would be wasteful.
    const onFocus = () => check();
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  if (enabled !== false) return null;

  const isAdmin =
    ((session?.user as Record<string, unknown> | undefined)?.role as
      | string
      | undefined) === "admin";

  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      <PauseCircle className="h-3.5 w-3.5 shrink-0" />
      <span>
        Publishing is paused — approved and scheduled content will wait until
        it is resumed.
      </span>
      {isAdmin && (
        <Link
          href="/system#publishing"
          className="font-medium underline underline-offset-2 hover:no-underline"
        >
          Manage
        </Link>
      )}
    </div>
  );
}
