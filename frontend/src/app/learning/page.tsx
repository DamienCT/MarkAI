"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { statusColor, formatRelativeTime } from "@/lib/utils";
import type { Adaptation } from "@/types";

export default function LearningPage() {
  const [adaptations, setAdaptations] = useState<Adaptation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchAdaptations() {
      try {
        const data = await api.get<Adaptation[]>("/api/v1/learning/adaptations", { limit: 50 });
        setAdaptations(data);
      } catch {
        // Handle error
      } finally {
        setLoading(false);
      }
    }
    fetchAdaptations();
  }, []);

  const handleApprove = async (id: string) => {
    try {
      await api.put(`/api/v1/learning/adaptations/${id}`, { status: "approved" });
      setAdaptations((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: "approved" } : a))
      );
    } catch {
      // Handle error
    }
  };

  const handleReject = async (id: string) => {
    try {
      await api.put(`/api/v1/learning/adaptations/${id}`, { status: "rejected" });
      setAdaptations((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: "rejected" } : a))
      );
    } catch {
      // Handle error
    }
  };

  const tiers = ["post", "campaign", "strategy"] as const;

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
      <div>
        <h1 className="text-3xl font-bold">System Learning</h1>
        <p className="text-muted-foreground">AI-driven adaptations and strategy refinements</p>
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
            <p className="text-3xl font-bold">
              {adaptations.filter((a) => a.status === "proposed").length}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Applied</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">
              {adaptations.filter((a) => a.status === "applied").length}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Avg Confidence</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">
              {adaptations.length > 0
                ? (
                    (adaptations.reduce((sum, a) => sum + a.confidence_score, 0) /
                      adaptations.length) *
                    100
                  ).toFixed(0)
                : 0}
              %
            </p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="post">
        <TabsList>
          {tiers.map((tier) => (
            <TabsTrigger key={tier} value={tier} className="capitalize">
              {tier} Level
            </TabsTrigger>
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
                          <Badge variant="outline">
                            {Math.round(adaptation.confidence_score * 100)}% confidence
                          </Badge>
                          <Badge className={statusColor(adaptation.status)}>{adaptation.status}</Badge>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent>
                      {adaptation.evidence.length > 0 && (
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
                        <span className="text-xs text-muted-foreground">
                          {formatRelativeTime(adaptation.created_at)}
                        </span>
                        {adaptation.status === "proposed" && (
                          <div className="flex gap-2">
                            <Button size="sm" variant="outline" onClick={() => handleReject(adaptation.id)}>
                              Reject
                            </Button>
                            <Button size="sm" onClick={() => handleApprove(adaptation.id)}>
                              Approve
                            </Button>
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
