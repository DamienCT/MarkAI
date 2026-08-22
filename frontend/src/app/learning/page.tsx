"use client";

import React, { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import { Info, TriangleAlert } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isAuthError } from "@/lib/api";
import { useRequireRole } from "@/lib/hooks";
import { statusColor, formatRelativeTime } from "@/lib/utils";
import type { Adaptation } from "@/types";

const TIER_LABELS: Record<number, "post" | "campaign" | "strategy"> = {
  1: "post", // low risk: timing, hashtags, minor caption tweaks
  2: "campaign", // medium risk: tone shifts, targeting, format changes
  3: "strategy", // major: pillar restructuring, platform strategy
};

function tierName(a: Adaptation): "post" | "campaign" | "strategy" {
  return (typeof a.tier === "number" ? TIER_LABELS[a.tier] : undefined) ?? "campaign";
}

function confidenceOf(a: Adaptation): number {
  const c = a.confidence;
  return typeof c === "number" && !Number.isNaN(c) ? c : 0.5;
}

// Rows still awaiting a human decision (mirrors the backend's CAS guard).
function isDecidable(a: Adaptation): boolean {
  return a.status === "proposed" || a.status === "auto_applied";
}

export default function LearningPage() {
  useRequireRole("editor"); // redirects unauthorized users as a side effect
  const { data: session } = useSession();
  const [adaptations, setAdaptations] = useState<Adaptation[]>([]);
  const [loading, setLoading] = useState(true);
  const [bulkApplying, setBulkApplying] = useState(false);

  // Decisions are manager/admin only server-side — hide the buttons below that.
  const userRole =
    (session?.user as Record<string, unknown> | undefined)?.role as string | undefined;
  const canDecide = userRole === "manager" || userRole === "admin";

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchAdaptations() {
      try {
        const data = await api.get<Adaptation[]>("/api/v1/learning/adaptations", { limit: 50 }, { signal });
        setAdaptations(data);
      } catch (err) {
        // Session expiry: the sign-in redirect is already underway — don't
        // flash a misleading load-failure toast over it.
        if (!isAuthError(err)) toast.error("Failed to load adaptations");
      } finally {
        setLoading(false);
      }
    }
    fetchAdaptations();

    return () => controller.abort();
  }, []);

  const handleDecision = async (id: string, action: "apply" | "reject") => {
    try {
      const res = await api.post<{ id: string; status: string }>(
        `/api/v1/learning/adaptations/${id}/decision`,
        { action }
      );
      setAdaptations((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: res.status } : a))
      );
      toast.success(action === "apply" ? "Recommendation applied" : "Recommendation rejected");
    } catch (err: unknown) {
      const detail =
        (err as { detail?: string })?.detail || `Failed to ${action} recommendation`;
      toast.error(detail);
    }
  };

  const handleBulkApplyTier1 = async () => {
    const postProposed = adaptations.filter(
      (a) => tierName(a) === "post" && isDecidable(a)
    );
    if (postProposed.length === 0) {
      toast.info("No proposed post-level recommendations to apply");
      return;
    }
    setBulkApplying(true);
    try {
      const results = await Promise.allSettled(
        postProposed.map((a) =>
          api.post(`/api/v1/learning/adaptations/${a.id}/decision`, { action: "apply" })
        )
      );
      const succeeded = results.filter((r) => r.status === "fulfilled").length;
      const failed = results.filter((r) => r.status === "rejected").length;

      setAdaptations((prev) =>
        prev.map((a) => {
          if (tierName(a) === "post" && isDecidable(a)) {
            const result = results[postProposed.findIndex((p) => p.id === a.id)];
            if (result?.status === "fulfilled") {
              return { ...a, status: "applied" };
            }
          }
          return a;
        })
      );

      if (failed === 0) {
        toast.success(`Applied ${succeeded} post-level recommendation(s)`);
      } else {
        toast.warning(`Applied ${succeeded}, failed ${failed}`);
      }
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to bulk apply";
      toast.error(detail);
    } finally {
      setBulkApplying(false);
    }
  };

  const tiers = ["post", "campaign", "strategy"] as const;

  const postProposedCount = adaptations.filter(
    (a) => tierName(a) === "post" && isDecidable(a)
  ).length;

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">System Learning</h1>
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-3xl font-bold">System Learning</h1>
            <Badge variant="outline" className="border-amber-400 text-amber-700 dark:border-amber-600 dark:text-amber-400">
              Experimental
            </Badge>
          </div>
          <p className="text-muted-foreground">AI-driven adaptations and strategy refinements</p>
        </div>
        {canDecide && postProposedCount > 0 && (
          <Button onClick={handleBulkApplyTier1} disabled={bulkApplying}>
            {bulkApplying
              ? "Applying..."
              : `Apply All Tier 1 (${postProposedCount})`}
          </Button>
        )}
      </div>

      {/* Experimental Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-950">
        <TriangleAlert className="h-5 w-5 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-800 dark:text-amber-200">
          <span className="font-semibold">Experimental</span> — recommendations only, nothing is auto-applied.
          Every adaptation stays proposed until a person applies or rejects it here.
        </p>
      </div>

      {/* Info Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950">
        <Info className="h-5 w-5 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
        <p className="text-sm text-blue-800 dark:text-blue-200">
          AI agents analyze content performance and propose improvements. Review and apply recommendations to help the system learn.
          Post-level changes can be bulk-applied; campaign and strategy changes require individual review.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Adaptations</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{adaptations.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Proposed</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{adaptations.filter((a) => a.status === "proposed").length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Applied</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{adaptations.filter((a) => a.status === "applied").length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Avg Confidence</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">
              {adaptations.length > 0
                ? ((adaptations.reduce((sum, a) => sum + confidenceOf(a), 0) / adaptations.length) * 100).toFixed(0)
                : 0}%
            </p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="post">
        <TabsList>
          {tiers.map((tier) => (
            <TabsTrigger key={tier} value={tier} className="capitalize">{tier} Level</TabsTrigger>
          ))}
        </TabsList>

        {tiers.map((tier) => (
          <TabsContent key={tier} value={tier} className="mt-6 space-y-4">
            {adaptations.filter((a) => tierName(a) === tier).length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center">
                  <p className="text-muted-foreground">No {tier}-level adaptations</p>
                </CardContent>
              </Card>
            ) : (
              adaptations
                .filter((a) => tierName(a) === tier)
                .map((adaptation) => (
                  <Card key={adaptation.id}>
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <div>
                          <CardTitle className="text-base">
                            {`Tier ${typeof adaptation.tier === "number" ? adaptation.tier : 2} recommendation`}
                          </CardTitle>
                          <CardDescription>{adaptation.adapted_text}</CardDescription>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">{Math.round(confidenceOf(adaptation) * 100)}% confidence</Badge>
                          <Badge className={statusColor(adaptation.status)}>{adaptation.status}</Badge>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent>
                      {/* What Changed section */}
                      {adaptation.adapted_text && (
                        <div className="mb-4 rounded-md border p-3 bg-muted/30">
                          <p className="text-xs font-medium mb-2">What changed</p>
                          <div className="space-y-2">
                            <div>
                              <p className="text-xs text-muted-foreground mb-1">Recommendation:</p>
                              <p className="text-xs bg-green-50 dark:bg-green-950/30 rounded-sm px-2 py-1 border border-green-200 dark:border-green-900">
                                {adaptation.adapted_text}
                              </p>
                            </div>
                            {adaptation.adapted_headline && (
                              <div>
                                <p className="text-xs text-muted-foreground mb-1">Adapted headline:</p>
                                <p className="text-xs bg-green-50 dark:bg-green-950/30 rounded-sm px-2 py-1 border border-green-200 dark:border-green-900">
                                  {adaptation.adapted_headline}
                                </p>
                              </div>
                            )}
                            {adaptation.adapted_hashtags && adaptation.adapted_hashtags.length > 0 && (
                              <div>
                                <p className="text-xs text-muted-foreground mb-1">Adapted hashtags:</p>
                                <div className="flex flex-wrap gap-1">
                                  {adaptation.adapted_hashtags.map((tag, i) => (
                                    <Badge key={i} variant="outline" className="text-[10px]">{tag}</Badge>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted-foreground">{formatRelativeTime(adaptation.created_at)}</span>
                        {canDecide && isDecidable(adaptation) && (
                          <div className="flex gap-2">
                            <Button size="sm" variant="outline" onClick={() => handleDecision(adaptation.id, "reject")}>Reject</Button>
                            <Button size="sm" onClick={() => handleDecision(adaptation.id, "apply")}>Apply</Button>
                          </div>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
