"use client";

import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isAuthError } from "@/lib/api";
import { useRequireRole } from "@/lib/hooks";
import type { AIModel, AIModelCategory } from "@/types";

interface DiscoverResult {
  discovered: number;
  updated: number;
  unavailable: number;
  total_from_api: number;
  total_in_db: number;
}

interface HealthStatus {
  status?: string;
  healthy_count?: number;
  unhealthy_count?: number;
  detail?: string;
}

interface ChannelFallback {
  channel: string;
  category: string;
  model_id: string;
  is_active: boolean;
}

// Channels that support a per-channel image-gen fallback. Must mirror
// SUPPORTED_FALLBACK_CHANNELS in backend/app/api/v1/providers.py.
const FALLBACK_CHANNELS: { id: string; label: string }[] = [
  { id: "instagram", label: "Instagram" },
  { id: "facebook", label: "Facebook" },
  { id: "linkedin", label: "LinkedIn" },
];

export default function ProvidersPage() {
  useRequireRole("admin"); // redirects unauthorized users as a side effect
  const [categories, setCategories] = useState<AIModelCategory[]>([]);
  const [modelsByCategory, setModelsByCategory] = useState<Record<string, AIModel[]>>({});
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [discoverResult, setDiscoverResult] = useState<DiscoverResult | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [savingSlug, setSavingSlug] = useState<string | null>(null);
  const [totalModels, setTotalModels] = useState(0);
  const [channelFallbacks, setChannelFallbacks] = useState<Record<string, ChannelFallback>>({});
  const [savingFallback, setSavingFallback] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [cats, allModels] = await Promise.all([
        api.get<AIModelCategory[]>("/api/v1/providers/categories"),
        api.get<AIModel[]>("/api/v1/providers/models"),
      ]);

      setCategories(cats);
      setTotalModels(allModels.length);

      const grouped: Record<string, AIModel[]> = {};
      for (const model of allModels) {
        // Add to primary category
        if (model.category_id) {
          const cat = cats.find((c) => c.id === model.category_id);
          if (cat) {
            if (!grouped[cat.slug]) grouped[cat.slug] = [];
            grouped[cat.slug].push(model);
          }
        }
        // Add to additional categories from capabilities JSONB
        const additional = (model.capabilities as Record<string, unknown>)?.additional_categories;
        if (Array.isArray(additional)) {
          for (const slug of additional) {
            if (typeof slug === "string" && !grouped[slug]?.includes(model)) {
              if (!grouped[slug]) grouped[slug] = [];
              grouped[slug].push(model);
            }
          }
        }
      }
      setModelsByCategory(grouped);
    } catch (err) {
      // Session expiry: the sign-in redirect is already underway.
      if (!isAuthError(err)) toast.error("Failed to load AI models");
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

  const fetchFallbacks = useCallback(async () => {
    try {
      const rows = await api.get<ChannelFallback[]>(
        "/api/v1/providers/channel-fallbacks",
        { category: "image" }
      );
      const map: Record<string, ChannelFallback> = {};
      for (const row of rows) map[row.channel] = row;
      setChannelFallbacks(map);
    } catch {
      // Fallbacks are optional; ignore on error.
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchHealth();
    fetchFallbacks();
  }, [fetchData, fetchHealth, fetchFallbacks]);

  const handleDiscover = async () => {
    setDiscovering(true);
    setDiscoverResult(null);
    try {
      const result = await api.post<DiscoverResult>("/api/v1/providers/discover");
      setDiscoverResult(result);
      toast.success(
        `Discovery complete: ${result.discovered} new, ${result.updated} updated` +
        (result.total_from_api ? ` (${result.total_from_api} from API, ${result.total_in_db} total)` : "")
      );
      await fetchData();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Discovery failed";
      toast.error(detail);
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
      toast.success("Model selection saved");
      await fetchData();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update model";
      toast.error(detail);
    } finally {
      setSavingSlug(null);
    }
  };

  const handleFallbackChange = async (
    channel: string,
    category: string,
    patch: { model_id?: string; is_active?: boolean }
  ) => {
    const existing = channelFallbacks[channel];
    const model_id = patch.model_id ?? existing?.model_id ?? "";
    const is_active = patch.is_active ?? existing?.is_active ?? true;
    if (!model_id) {
      toast.error("Pick a model first");
      return;
    }
    setSavingFallback(channel);
    try {
      const updated = await api.put<ChannelFallback>(
        "/api/v1/providers/channel-fallbacks",
        { channel, category, model_id, is_active }
      );
      setChannelFallbacks((prev) => ({ ...prev, [channel]: updated }));
      toast.success(`Fallback for ${channel} saved`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to save fallback";
      toast.error(detail);
    } finally {
      setSavingFallback(null);
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
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold">AI Model Management</h1>
          <p className="text-muted-foreground">
            Select which AI model to use for each use case. Models are discovered automatically from providers.
          </p>
        </div>
        <Button onClick={handleDiscover} disabled={discovering}>
          {discovering ? "Discovering..." : "Discover Models"}
        </Button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="py-4">
            <div className="text-sm text-muted-foreground">Available Models</div>
            <div className="text-3xl font-bold">{totalModels}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="text-sm text-muted-foreground">Categories</div>
            <div className="text-3xl font-bold">{categories.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="text-sm text-muted-foreground">LiteLLM Proxy Status</div>
            <div className="mt-1">
              {health ? (
                <Badge variant={health.status === "healthy" || health.status === "connected" ? "default" : "destructive"}>
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
              Discovery complete: <strong>{discoverResult.discovered}</strong> new models found,{" "}
              <strong>{discoverResult.updated}</strong> updated,{" "}
              <strong>{discoverResult.unavailable}</strong> marked unavailable.
              {discoverResult.total_from_api > 0 && (
                <> Fetched <strong>{discoverResult.total_from_api}</strong> models from OpenAI API ({discoverResult.total_in_db} total available).</>
              )}
              {discoverResult.total_from_api === 0 && discoverResult.discovered === 0 && (
                <span className="text-destructive"> OpenAI API returned 0 models — check your OPENAI_API_KEY.</span>
              )}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Category cards */}
      {categories.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">No model categories found. Run model discovery to get started.</p>
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
                    <CardTitle className="text-lg">{category.display_name}</CardTitle>
                    {activeModel ? (
                      <Badge variant="default">Active</Badge>
                    ) : (
                      <Badge variant="outline">No selection</Badge>
                    )}
                  </div>
                  {category.description && <CardDescription>{category.description}</CardDescription>}
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-1">
                    <label className="text-sm font-medium text-muted-foreground">Active Model</label>
                    <p className="text-sm font-mono">{activeModel ? activeModel.model_id : "Using default"}</p>
                  </div>
                  <div className="space-y-1">
                    <label htmlFor={`model-${category.slug}`} className="text-sm font-medium text-muted-foreground">
                      Change Model
                    </label>
                    <select
                      id={`model-${category.slug}`}
                      className="flex h-9 w-full rounded-md border border-input bg-background text-foreground px-3 py-1 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>option]:bg-background [&>option]:text-foreground"
                      value={activeModel?.id ?? ""}
                      disabled={isSaving || availableModels.length === 0}
                      onChange={(e) => {
                        if (e.target.value) handleModelChange(category.slug, e.target.value);
                      }}
                    >
                      <option value="">
                        {availableModels.length === 0 ? "No models available" : "Select a model..."}
                      </option>
                      {availableModels.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.model_id}
                          {model.display_name && model.display_name !== model.model_id ? ` (${model.display_name})` : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {availableModels.length} model{availableModels.length !== 1 ? "s" : ""} available
                  </div>
                  {isSaving && <p className="text-xs text-muted-foreground animate-pulse">Saving...</p>}

                  {category.slug === "image" && (
                    <div className="pt-3 mt-3 border-t space-y-2">
                      <div className="text-sm font-medium">Fallback per channel</div>
                      <p className="text-xs text-muted-foreground">
                        Used if the active model fails for the channel. Falls through to{" "}
                        <span className="font-mono">gpt-image-1</span> as a last resort.
                      </p>
                      {FALLBACK_CHANNELS.map((ch) => {
                        const fb = channelFallbacks[ch.id];
                        const savingThis = savingFallback === ch.id;
                        return (
                          <div
                            key={ch.id}
                            className="flex items-center gap-2 rounded-md border p-2"
                          >
                            <span className="text-xs font-medium w-20 shrink-0">
                              {ch.label}
                            </span>
                            <select
                              className="flex h-8 flex-1 min-w-0 rounded-md border border-input bg-background text-foreground px-2 text-xs disabled:cursor-not-allowed disabled:opacity-50 [&>option]:bg-background [&>option]:text-foreground"
                              value={fb?.model_id ?? ""}
                              disabled={savingThis || availableModels.length === 0}
                              onChange={(e) =>
                                handleFallbackChange(ch.id, "image", {
                                  model_id: e.target.value,
                                })
                              }
                            >
                              <option value="">
                                {availableModels.length === 0 ? "No models" : "Pick a model..."}
                              </option>
                              {availableModels.map((m) => (
                                <option key={m.id} value={m.model_id}>
                                  {m.model_id}
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              disabled={savingThis || !fb?.model_id}
                              onClick={() =>
                                handleFallbackChange(ch.id, "image", {
                                  is_active: !(fb?.is_active ?? false),
                                })
                              }
                              className={`shrink-0 inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition-colors disabled:opacity-50 ${
                                fb?.is_active
                                  ? "bg-emerald-500/15 text-emerald-700 hover:bg-emerald-500/25 dark:text-emerald-300"
                                  : "bg-muted text-muted-foreground hover:bg-muted/80"
                              }`}
                              title={
                                !fb?.model_id
                                  ? "Pick a model first"
                                  : fb?.is_active
                                    ? "Active — click to disable"
                                    : "Inactive — click to enable"
                              }
                            >
                              {fb?.is_active ? "Active" : "Inactive"}
                            </button>
                          </div>
                        );
                      })}
                    </div>
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
