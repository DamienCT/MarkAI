"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Info } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useRequireRole } from "@/lib/hooks";
import { statusColor, formatRelativeTime } from "@/lib/utils";
import type { Adaptation } from "@/types";

export default function LearningPage() {
  const { hasAccess, loading: roleLoading } = useRequireRole("editor");
  const [adaptations, setAdaptations] = useState<Adaptation[]>([]);
  const [loading, setLoading] = useState(true);
  const [bulkApproving, setBulkApproving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchAdaptations() {
      try {
        const data = await api.get<Adaptation[]>("/api/v1/learning/adaptations", { limit: 50 }, { signal });
        setAdaptations(data);
      } catch {
        toast.error("Failed to load adaptations");
      } finally {
        setLoading(false);
      }
    }
    fetchAdaptations();

    return () => controller.abort();
  }, []);

  const handleApprove = async (id: string) => {
    try {
      await api.put(`/api/v1/learning/adaptations/${id}`, { status: "approved" });
      setAdaptations((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: "approved" } : a))
      );
      toast.success("Adaptation approved");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to approve adaptation";
      toast.error(detail);
    }
  };

  const handleReject = async (id: string) => {
    try {
      await api.put(`/api/v1/learning/adaptations/${id}`, { status: "rejected" });
      setAdaptations((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: "rejected" } : a))
      );
      toast.success("Adaptation rejected");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to reject adaptation";
      toast.error(detail);
    }
  };

  const handleBulkApproveTier1 = async () => {
    const postProposed = adaptations.filter(
      (a) => a.tier === "post" && a.status === "proposed"
    );
    if (postProposed.length === 0) {
      toast.info("No proposed post-level adaptations to approve");
      return;
    }
    setBulkApproving(true);
    try {
      const results = await Promise.allSettled(
        postProposed.map((a) =>
          api.put(`/api/v1/learning/adaptations/${a.id}`, { status: "approved" })
        )
      );
      const succeeded = results.filter((r) => r.status === "fulfilled").length;
      const failed = results.filter((r) => r.status === "rejected").length;

      setAdaptations((prev) =>
        prev.map((a) => {
          if (a.tier === "post" && a.status === "proposed") {
            const result = results[postProposed.findIndex((p) => p.id === a.id)];
            if (result?.status === "fulfilled") {
              return { ...a, status: "approved" };
            }
          }
          return a;
        })
      );

      if (failed === 0) {
        toast.success(`Approved ${succeeded} post-level adaptation(s)`);
      } else {
        toast.warning(`Approved ${succeeded}, failed ${failed}`);
      }
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to bulk approve";
      toast.error(detail);
    } finally {
      setBulkApproving(false);
    }
  };

  const tiers = ["post", "campaign", "strategy"] as const;

  const postProposedCount = adaptations.filter(
    (a) => a.tier === "post" && a.status === "proposed"
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
          <h1 className="text-3xl font-bold">System Learning</h1>
          <p className="text-muted-foreground">AI-driven adaptations and strategy refinements</p>
        </div>
        {postProposedCount > 0 && (
          <Button onClick={handleBulkApproveTier1} disabled={bulkApproving}>
            {bulkApproving
              ? "Approving..."
              : `Approve All Tier 1 (${postProposedCount})`}
          </Button>
        )}
      </div>

      {/* Info Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950">
        <Info className="h-5 w-5 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
        <p className="text-sm text-blue-800 dark:text-blue-200">
          AI agents analyze content performance and propose improvements. Review and approve adaptations to help the system learn.
          Post-level changes are safe to auto-approve, while campaign and strategy changes require manual review.
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
                ? ((adaptations.reduce((sum, a) => sum + a.confidence_score, 0) / adaptations.length) * 100).toFixed(0)
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
            {adaptations.filter((a) => a.tier === tier).length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center">
                  <p className="text-muted-foreground">No {tier}-level adaptations</p>
                </CardContent>
              </Card>
            ) : (
              adaptations
                .filter((a) => a.tier === tier)
                .map((adaptation) => (
                  <Card key={adaptation.id}>
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <div>
                          <CardTitle className="text-base">{adaptation.category}</CardTitle>
                          <CardDescription>{adaptation.description}</CardDescription>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">{Math.round(adaptation.confidence_score * 100)}% confidence</Badge>
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
                            {adaptation.adaptation_notes && (
                              <div>
                                <p className="text-xs text-muted-foreground mb-1">Original context:</p>
                                <p className="text-xs bg-red-50 dark:bg-red-950/30 rounded-sm px-2 py-1 border border-red-200 dark:border-red-900">
                                  {adaptation.adaptation_notes}
                                </p>
                              </div>
                            )}
                            <div>
                              <p className="text-xs text-muted-foreground mb-1">Adapted text:</p>
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

                      {adaptation.evidence && adaptation.evidence.length > 0 && (
                        <div className="mb-4">
                          <p className="text-xs font-medium text-muted-foreground mb-1">Evidence:</p>
                          <ul className="text-xs text-muted-foreground space-y-1">
                            {adaptation.evidence.map((e, i) => (
                              <li key={i}>- {e}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted-foreground">{formatRelativeTime(adaptation.created_at)}</span>
                        {adaptation.status === "proposed" && (
                          <div className="flex gap-2">
                            <Button size="sm" variant="outline" onClick={() => handleReject(adaptation.id)}>Reject</Button>
                            <Button size="sm" onClick={() => handleApprove(adaptation.id)}>Approve</Button>
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
