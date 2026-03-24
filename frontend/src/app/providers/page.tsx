"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { AIModel, AIModelCategory } from "@/types";

interface DiscoverResult {
  discovered: number;
  updated: number;
  unavailable: number;
}

interface HealthStatus {
  status?: string;
  healthy_count?: number;
  unhealthy_count?: number;
  detail?: string;
}

export default function ProvidersPage() {
  const [categories, setCategories] = useState<AIModelCategory[]>([]);
  const [modelsByCategory, setModelsByCategory] = useState<
    Record<string, AIModel[]>
  >({});
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [discoverResult, setDiscoverResult] = useState<DiscoverResult | null>(
    null
  );
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [savingSlug, setSavingSlug] = useState<string | null>(null);
  const [totalModels, setTotalModels] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);

      // Fetch categories and all models in parallel
      const [cats, allModels] = await Promise.all([
        api.get<AIModelCategory[]>("/api/v1/providers/categories"),
        api.get<AIModel[]>("/api/v1/providers/models"),
      ]);

      setCategories(cats);
      setTotalModels(allModels.length);

      // Group models by category
      const grouped: Record<string, AIModel[]> = {};
      for (const model of allModels) {
        if (model.category_id) {
          // Find the category slug for this category_id
          const cat = cats.find((c) => c.id === model.category_id);
          if (cat) {
            if (!grouped[cat.slug]) grouped[cat.slug] = [];
            grouped[cat.slug].push(model);
          }
        }
      }
      setModelsByCategory(grouped);
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : typeof err === "object" && err !== null && "detail" in err
            ? String((err as { detail: string }).detail)
            : "Failed to load data";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      const h = await api.get<HealthStatus>("/api/v1/providers/health");
      setHealth(h);
    } catch {
      setHealth({ status: "unreachable" });
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchHealth();
  }, [fetchData, fetchHealth]);

  const handleDiscover = async () => {
    setDiscovering(true);
    setDiscoverResult(null);
    try {
      const result = await api.post<DiscoverResult>(
        "/api/v1/providers/discover"
      );
      setDiscoverResult(result);
      // Refresh data after discovery
      await fetchData();
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : typeof err === "object" && err !== null && "detail" in err
            ? String((err as { detail: string }).detail)
            : "Discovery failed";
      setError(message);
    } finally {
      setDiscovering(false);
    }
  };

  const handleModelChange = async (categorySlug: string, modelId: string) => {
    setSavingSlug(categorySlug);
    try {
      await api.put(`/api/v1/providers/active/${categorySlug}`, {
        model_id: modelId,
        is_active: true,
        priority: 0,
      });
      // Refresh categories to get the updated active model
      await fetchData();
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : typeof err === "object" && err !== null && "detail" in err
            ? String((err as { detail: string }).detail)
            : "Failed to update model";
      setError(message);
    } finally {
      setSavingSlug(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">AI Model Management</h1>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-56" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">AI Model Management</h1>
          <p className="text-muted-foreground">
            Select which AI model to use for each use case. Models are
            discovered automatically from providers.
          </p>
        </div>
        <Button onClick={handleDiscover} disabled={discovering}>
          {discovering ? "Discovering..." : "Discover Models"}
        </Button>
      </div>

      {/* Error banner */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="py-4">
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="py-4">
            <div className="text-sm text-muted-foreground">
              Available Models
            </div>
            <div className="text-2xl font-bold">{totalModels}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="text-sm text-muted-foreground">Categories</div>
            <div className="text-2xl font-bold">{categories.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="text-sm text-muted-foreground">
              LiteLLM Proxy Status
            </div>
            <div className="mt-1">
              {health ? (
                <Badge
                  variant={
                    health.status === "healthy" ||
                    health.status === "connected"
                      ? "default"
                      : "destructive"
                  }
                >
                  {health.status || "unknown"}
                </Badge>
              ) : (
                <Badge variant="outline">checking...</Badge>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Discovery result */}
      {discoverResult && (
        <Card className="border-primary/50 bg-primary/5">
          <CardContent className="py-4">
            <p className="text-sm">
              Discovery complete:{" "}
              <strong>{discoverResult.discovered}</strong> new models found,{" "}
              <strong>{discoverResult.updated}</strong> updated,{" "}
              <strong>{discoverResult.unavailable}</strong> marked unavailable.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Category cards */}
      {categories.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">
              No model categories found. Run model discovery to get started.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {categories.map((category) => {
            const availableModels = modelsByCategory[category.slug] || [];
            const activeModel = category.active_model;
            const isSaving = savingSlug === category.slug;

            return (
              <Card key={category.id}>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg">
                      {category.display_name}
                    </CardTitle>
                    {activeModel ? (
                      <Badge variant="default">Active</Badge>
                    ) : (
                      <Badge variant="outline">No selection</Badge>
                    )}
                  </div>
                  {category.description && (
                    <CardDescription>{category.description}</CardDescription>
                  )}
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Current model */}
                  <div className="space-y-1">
                    <label className="text-sm font-medium text-muted-foreground">
                      Active Model
                    </label>
                    <p className="text-sm font-mono">
                      {activeModel ? activeModel.model_id : "Using default"}
                    </p>
                  </div>

                  {/* Model selector */}
                  <div className="space-y-1">
                    <label
                      htmlFor={`model-${category.slug}`}
                      className="text-sm font-medium text-muted-foreground"
                    >
                      Change Model
                    </label>
                    <select
                      id={`model-${category.slug}`}
                      className="flex h-9 w-full rounded-md border border-input bg-background text-foreground px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>option]:bg-background [&>option]:text-foreground"
                      value={activeModel?.id ?? ""}
                      disabled={isSaving || availableModels.length === 0}
                      onChange={(e) => {
                        if (e.target.value) {
                          handleModelChange(category.slug, e.target.value);
                        }
                      }}
                    >
                      <option value="">
                        {availableModels.length === 0
                          ? "No models available"
                          : "Select a model..."}
                      </option>
                      {availableModels.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.model_id}
                          {model.display_name &&
                          model.display_name !== model.model_id
                            ? ` (${model.display_name})`
                            : ""}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Model count */}
                  <div className="text-xs text-muted-foreground">
                    {availableModels.length} model
                    {availableModels.length !== 1 ? "s" : ""} available
                  </div>

                  {isSaving && (
                    <p className="text-xs text-muted-foreground animate-pulse">
                      Saving...
                    </p>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
