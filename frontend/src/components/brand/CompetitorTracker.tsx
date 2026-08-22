"use client";

import React, { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ExternalLink, Plus, Pencil, Trash2, Sparkles, Loader2, X, Save,
} from "lucide-react";
import { api, isAuthError } from "@/lib/api";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { Competitor } from "@/types";

interface CompetitorTrackerProps {
  brandId: string;
  competitors: Competitor[];
  onCompetitorsChange?: () => void;
}

interface CompetitorInsight {
  competitor_name: string;
  recent_posts: number;
  avg_engagement: number;
  trending_topics: string[];
  last_updated: string;
}

type CompetitorWithId = Competitor;

const SOCIAL_PLATFORMS = [
  { key: "instagram", label: "Instagram" },
  { key: "facebook", label: "Facebook" },
  { key: "linkedin", label: "LinkedIn" },
  { key: "x", label: "X (Twitter)" },
  { key: "tiktok", label: "TikTok" },
];

const emptyForm = {
  name: "",
  website_url: "",
  social_handles: {} as Record<string, string>,
  notes: "",
};

export function CompetitorTracker({ brandId, competitors, onCompetitorsChange }: CompetitorTrackerProps) {
  const [insights, setInsights] = useState<CompetitorInsight[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // Fetch local competitor list with IDs
  const [competitorList, setCompetitorList] = useState<CompetitorWithId[]>(competitors);

  useEffect(() => {
    setCompetitorList(competitors);
  }, [competitors]);

  useEffect(() => {
    async function fetchCompetitorData() {
      try {
        // Single fetch for both competitor list and insight data (same endpoint)
        const data = await api.get<(CompetitorWithId & Partial<CompetitorInsight>)[]>(
          `/api/v1/brands/${brandId}/competitors`
        );
        setCompetitorList(data);
        // Extract insight fields where they exist
        const insightData: CompetitorInsight[] = data
          .filter((d) => d.recent_posts !== undefined || d.avg_engagement !== undefined)
          .map((d) => ({
            competitor_name: d.name,
            recent_posts: d.recent_posts ?? 0,
            avg_engagement: d.avg_engagement ?? 0,
            trending_topics: d.trending_topics ?? [],
            last_updated: d.last_updated ?? "",
          }));
        setInsights(insightData);
      } catch (err) {
        // Session expiry: the sign-in redirect is already underway.
        if (!isAuthError(err)) toast.error("Failed to load competitors");
      }
    }
    fetchCompetitorData();
  }, [brandId]);

  const resetForm = () => {
    setForm({ ...emptyForm });
    setShowForm(false);
    setEditingId(null);
  };

  const handleEdit = (comp: CompetitorWithId) => {
    setForm({
      name: comp.name,
      website_url: comp.website_url || "",
      social_handles: { ...(comp.social_handles || {}) },
      notes: comp.notes || "",
    });
    setEditingId(comp.id || null);
    setShowForm(true);
  };

  const handleSocialChange = (platform: string, value: string) => {
    setForm((prev) => {
      const handles = { ...prev.social_handles };
      if (value) {
        handles[platform] = value;
      } else {
        delete handles[platform];
      }
      return { ...prev, social_handles: handles };
    });
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) {
      toast.error("Competitor name is required");
      return;
    }

    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        website_url: form.website_url.trim() || null,
        social_handles: Object.keys(form.social_handles).length > 0 ? form.social_handles : null,
        notes: form.notes.trim() || null,
      };

      if (editingId) {
        await api.put(`/api/v1/brands/${brandId}/competitors/${editingId}`, payload);
        toast.success("Competitor updated");
      } else {
        await api.post(`/api/v1/brands/${brandId}/competitors`, payload);
        toast.success("Competitor added");
      }

      // Refresh list
      const data = await api.get<CompetitorWithId[]>(`/api/v1/brands/${brandId}/competitors`);
      setCompetitorList(data);
      resetForm();
      onCompetitorsChange?.();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to save competitor";
      toast.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const executeDelete = useCallback(async (competitorId: string) => {
    setDeleting(competitorId);
    try {
      await api.delete(`/api/v1/brands/${brandId}/competitors/${competitorId}`);
      toast.success("Competitor deleted");
      const data = await api.get<CompetitorWithId[]>(`/api/v1/brands/${brandId}/competitors`);
      setCompetitorList(data);
      onCompetitorsChange?.();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to delete competitor";
      toast.error(detail);
    } finally {
      setDeleting(null);
    }
  }, [brandId, onCompetitorsChange]);

  const handleAutoDiscover = async () => {
    setTriggering(true);
    try {
      await api.post(`/api/v1/intelligence/discover-competitors`, { brand_id: brandId });
      toast.success("Auto-discover started. New competitors will appear in a moment.");
      // Discovery is async (web search + LLM, ~10-30s) and does NOT regenerate
      // any document — just refresh the competitor list a few times.
      const refetch = async () => {
        try {
          const data = await api.get<CompetitorWithId[]>(`/api/v1/brands/${brandId}/competitors`);
          setCompetitorList(data);
          onCompetitorsChange?.();
        } catch {
          /* ignore transient refetch errors */
        }
      };
      [10000, 20000, 30000].forEach((ms) => setTimeout(refetch, ms));
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to start auto-discover";
      toast.error(detail);
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg">Competitor Tracking</CardTitle>
              <CardDescription>Monitor competitor activity and performance</CardDescription>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={triggering}
                onClick={handleAutoDiscover}
              >
                {triggering ? (
                  <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-3 w-3" />
                )}
                Auto-discover
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  resetForm();
                  setShowForm(true);
                }}
              >
                <Plus className="mr-2 h-3 w-3" />
                Add Competitor
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Inline Form */}
          {showForm && (
            <div className="rounded-lg border p-4 mb-4 space-y-4 bg-muted/20">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium">
                  {editingId ? "Edit Competitor" : "Add Competitor"}
                </h4>
                <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={resetForm}>
                  <X className="h-4 w-4" />
                </Button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs">Name *</Label>
                  <Input
                    className="h-8 text-sm"
                    placeholder="Competitor name"
                    value={form.name}
                    onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Website URL</Label>
                  <Input
                    className="h-8 text-sm"
                    placeholder="https://competitor.com"
                    value={form.website_url}
                    onChange={(e) => setForm((prev) => ({ ...prev, website_url: e.target.value }))}
                  />
                </div>
              </div>

              <div>
                <Label className="text-xs mb-2 block">Social Handles</Label>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {SOCIAL_PLATFORMS.map((platform) => (
                    <div key={platform.key} className="space-y-1">
                      <Label className="text-[10px] text-muted-foreground">{platform.label}</Label>
                      <Input
                        className="h-7 text-xs"
                        placeholder={`@handle`}
                        value={form.social_handles[platform.key] || ""}
                        onChange={(e) => handleSocialChange(platform.key, e.target.value)}
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-1">
                <Label className="text-xs">Notes</Label>
                <Input
                  className="h-8 text-sm"
                  placeholder="Any relevant notes..."
                  value={form.notes}
                  onChange={(e) => setForm((prev) => ({ ...prev, notes: e.target.value }))}
                />
              </div>

              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={resetForm}>
                  Cancel
                </Button>
                <Button size="sm" disabled={saving} onClick={handleSubmit}>
                  {saving ? (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  ) : (
                    <Save className="mr-2 h-3 w-3" />
                  )}
                  {editingId ? "Update" : "Add"}
                </Button>
              </div>
            </div>
          )}

          {/* Competitor List */}
          {competitorList.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              No competitors configured for this brand
            </p>
          ) : (
            <div className="space-y-4">
              {competitorList.map((competitor, i) => {
                const insight = insights.find(
                  (ins) => ins.competitor_name.toLowerCase() === competitor.name.toLowerCase()
                );
                return (
                  <div key={competitor.id || i} className="rounded-md border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <h4 className="font-medium">{competitor.name}</h4>
                        {competitor.website_url && (
                          <a
                            href={competitor.website_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-muted-foreground hover:text-foreground"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(competitor.social_handles || {}).map(([platform, handle]) => (
                            <Badge key={platform} variant="outline" className="text-[10px] capitalize">
                              {platform}: @{handle}
                            </Badge>
                          ))}
                        </div>
                        {competitor.id && (
                          <div className="flex gap-1 ml-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0"
                              onClick={() => handleEdit(competitor)}
                            >
                              <Pencil className="h-3 w-3" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                              disabled={deleting === competitor.id}
                              onClick={() => setDeleteConfirmId(competitor.id!)}
                            >
                              {deleting === competitor.id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Trash2 className="h-3 w-3" />
                              )}
                            </Button>
                          </div>
                        )}
                      </div>
                    </div>

                    {insight && (
                      <div className="grid grid-cols-2 gap-4 text-sm">
                        <div>
                          <p className="text-muted-foreground">Recent Posts</p>
                          <p className="font-medium">{insight.recent_posts}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Avg Engagement</p>
                          <p className="font-medium">{(insight.avg_engagement * 100).toFixed(2)}%</p>
                        </div>
                        {insight.trending_topics.length > 0 && (
                          <div className="col-span-2">
                            <p className="text-muted-foreground mb-1">Trending Topics</p>
                            <div className="flex flex-wrap gap-1">
                              {insight.trending_topics.map((topic, j) => (
                                <Badge key={j} variant="secondary" className="text-xs">
                                  {topic}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {competitor.notes && (
                      <p className="text-xs text-muted-foreground">{competitor.notes}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={deleteConfirmId !== null}
        onOpenChange={(open) => { if (!open) setDeleteConfirmId(null); }}
        title="Delete Competitor"
        description="Are you sure you want to delete this competitor?"
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => {
          if (deleteConfirmId) executeDelete(deleteConfirmId);
        }}
      />
    </div>
  );
}
