"use client";

import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Role hierarchy: admin > manager > editor > viewer.
 * Returns true if the user's role is at least `minRole`.
 * Redirects to "/" if the user lacks the required role.
 */

const ROLE_LEVELS: Record<string, number> = {
  viewer: 10,
  editor: 60,
  manager: 80,
  admin: 100,
};

export function useRequireRole(minRole: "viewer" | "editor" | "manager" | "admin") {
  const { data: session, status } = useSession();
  const router = useRouter();

  const userRole = (session?.user as Record<string, unknown> | undefined)?.role as string | undefined;
  const userLevel = ROLE_LEVELS[userRole ?? "viewer"] ?? 0;
  const requiredLevel = ROLE_LEVELS[minRole] ?? 0;
  const hasAccess = userLevel >= requiredLevel;

  useEffect(() => {
    // Wait until session is loaded before redirecting
    if (status === "loading") return;
    if (status === "unauthenticated" || !hasAccess) {
      router.replace("/");
    }
  }, [status, hasAccess, router]);

  return { hasAccess, loading: status === "loading" };
}
