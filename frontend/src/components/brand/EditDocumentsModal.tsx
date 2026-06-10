"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { X, Trash2, Plus, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

// Full weekday names (stored in best_days); displayed as 3-letter chips.
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const SHORT: Record<string, string> = {
  Monday: "Mon", Tuesday: "Tue", Wednesday: "Wed", Thursday: "Thu",
  Friday: "Fri", Saturday: "Sat", Sunday: "Sun",
};
const CHANNEL_DOT: Record<string, string> = {
  instagram: "#E1306C", facebook: "#1877F2", linkedin: "#0A66C2",
  twitter: "#1DA1F2", x: "#111827", tiktok: "#111827",
};

type Cadence = Record<string, { posts_per_week?: number; best_days?: string[] }>;
type Audience = string | { name?: string; description?: string };

interface OverridesData {
  cadence: Cadence;
  content_pillars: string[];
  target_audiences: Audience[];
  campaigns: string[];
  removed_campaigns: string[];
  content_format: string;
  brand_voice: string;
}

function audienceName(a: Audience): string {
  return typeof a === "string" ? a : a?.name || "";
}

export function EditDocumentsModal({
  brandId,
  open,
  onClose,
}: {
  brandId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [data, setData] = useState<OverridesData | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get<OverridesData>(`/api/v1/brands/${brandId}/overrides`)
      .then((d) =>
        setData({
          cadence: d.cadence || {},
          content_pillars: d.content_pillars || [],
          target_audiences: d.target_audiences || [],
          campaigns: d.campaigns || [],
          removed_campaigns: d.removed_campaigns || [],
          content_format: d.content_format || "posts_only",
          brand_voice: d.brand_voice || "",
        })
      )
      .catch(() => toast.error("Failed to load document settings"))
      .finally(() => setLoading(false));
  }, [open, brandId]);

  if (!open) return null;

  // ── mutators ──────────────────────────────────────────────
  const toggleDay = (ch: string, day: string) =>
    setData((d) => {
      if (!d) return d;
      const cur = d.cadence[ch] || {};
      const days = new Set(cur.best_days || []);
      if (days.has(day)) days.delete(day);
      else days.add(day);
      const best_days = WEEKDAYS.filter((w) => days.has(w));
      return {
        ...d,
        cadence: { ...d.cadence, [ch]: { ...cur, best_days, posts_per_week: best_days.length } },
      };
    });

  const setPillar = (i: number, v: string) =>
    setData((d) => d && { ...d, content_pillars: d.content_pillars.map((p, j) => (j === i ? v : p)) });
  const delPillar = (i: number) =>
    setData((d) => d && { ...d, content_pillars: d.content_pillars.filter((_, j) => j !== i) });
  const addPillar = () =>
    setData((d) => d && { ...d, content_pillars: [...d.content_pillars, "New pillar"] });

  const delAudience = (i: number) =>
    setData((d) => d && { ...d, target_audiences: d.target_audiences.filter((_, j) => j !== i) });

  const delCampaign = (name: string) =>
    setData((d) =>
      d && {
        ...d,
        campaigns: d.campaigns.filter((c) => c !== name),
        removed_campaigns: [...new Set([...d.removed_campaigns, name])],
      }
    );

  const setFormat = (f: string) => setData((d) => d && { ...d, content_format: f });

  // ── persistence ───────────────────────────────────────────
  async function persist(): Promise<boolean> {
    if (!data) return false;
    const body = {
      cadence: data.cadence,
      content_pillars: data.content_pillars,
      target_audiences: data.target_audiences.map((a) =>
        typeof a === "string" ? { name: a } : a
      ),
      content_format: data.content_format,
      removed_campaigns: data.removed_campaigns,
    };
    await api.put(`/api/v1/brands/${brandId}/overrides`, body);
    return true;
  }

  async function handleSave() {
    setSaving(true);
    try {
      await persist();
      toast.success("Settings saved");
      onClose();
    } catch {
      toast.error("Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  async function handleApply() {
    setSaving(true);
    try {
      await persist();
      await api.post(`/api/v1/brands/${brandId}/overrides/apply`, {});
      toast.success("Re-planning started — the calendar will update shortly");
      onClose();
    } catch {
      toast.error("Failed to apply changes");
    } finally {
      setSaving(false);
    }
  }

  const cadenceChannels = data ? Object.keys(data.cadence) : [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-auto bg-black/50 p-4 sm:p-10"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-3xl rounded-2xl bg-background shadow-2xl">
        {/* header */}
        <div className="sticky top-0 flex items-center justify-between border-b bg-background px-6 py-4 rounded-t-2xl">
          <div>
            <h2 className="text-xl font-bold">Edit documents</h2>
            <p className="text-sm text-muted-foreground">Tune the levers the AI uses to generate content.</p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X className="h-5 w-5" />
          </Button>
        </div>

        {/* body */}
        <div className="max-h-[65vh] overflow-auto px-6 py-2">
          {loading || !data ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…
            </div>
          ) : (
            <>
              {/* Posting cadence */}
              <section className="border-b py-4">
                <p className="mb-3 text-sm font-bold">Posting cadence — pick the days, posts/week updates automatically</p>
                {cadenceChannels.length === 0 && (
                  <p className="text-sm text-muted-foreground">No cadence yet — generate the strategy first.</p>
                )}
                {cadenceChannels.map((ch) => {
                  const days = data.cadence[ch]?.best_days || [];
                  return (
                    <div key={ch} className="mb-2.5 rounded-xl border p-3">
                      <div className="mb-2 flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ background: CHANNEL_DOT[ch.toLowerCase()] || "#6366f1" }} />
                        <span className="flex-1 text-sm font-semibold capitalize">{ch}</span>
                        <span className="text-sm font-extrabold text-primary">{days.length}</span>
                        <span className="text-xs text-muted-foreground">/week</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {WEEKDAYS.map((w) => {
                          const on = days.includes(w);
                          return (
                            <button
                              key={w}
                              type="button"
                              onClick={() => toggleDay(ch, w)}
                              className={`rounded-full border px-2.5 py-1 text-xs transition ${
                                on ? "border-primary bg-primary text-primary-foreground" : "hover:border-primary"
                              }`}
                            >
                              {SHORT[w]}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </section>

              {/* Content format */}
              <section className="border-b py-4">
                <p className="mb-3 text-sm font-bold">Content format</p>
                <div className="inline-flex overflow-hidden rounded-lg border">
                  {[
                    { v: "posts_only", label: "Posts only" },
                    { v: "mixed", label: "Mixed (reels, carousel…)" },
                  ].map((o) => (
                    <button
                      key={o.v}
                      type="button"
                      onClick={() => setFormat(o.v)}
                      className={`px-3.5 py-1.5 text-sm font-semibold ${
                        data.content_format === o.v ? "bg-primary text-primary-foreground" : "hover:bg-accent"
                      }`}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              </section>

              {/* Pillars + audiences */}
              <section className="grid grid-cols-1 gap-6 border-b py-4 sm:grid-cols-2">
                <div>
                  <p className="mb-3 text-sm font-bold">Content pillars</p>
                  {data.content_pillars.map((p, i) => (
                    <div key={i} className="mb-2 flex items-center gap-2 rounded-lg border p-2">
                      <input
                        className="flex-1 bg-transparent text-sm outline-none"
                        value={p}
                        onChange={(e) => setPillar(i, e.target.value)}
                      />
                      <button className="text-muted-foreground hover:text-destructive" onClick={() => delPillar(i)}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                  <button
                    className="mt-1 w-full rounded-lg border border-dashed border-primary/40 py-2 text-xs font-bold text-primary hover:bg-primary/5"
                    onClick={addPillar}
                  >
                    <Plus className="mr-1 inline h-3.5 w-3.5" /> Add pillar
                  </button>
                </div>
                <div>
                  <p className="mb-3 text-sm font-bold">Target audiences</p>
                  {data.target_audiences.map((a, i) => (
                    <div key={i} className="mb-2 flex items-center gap-2 rounded-lg border p-2">
                      <span className="flex-1 text-sm font-medium">{audienceName(a) || "Audience"}</span>
                      <button className="text-muted-foreground hover:text-destructive" onClick={() => delAudience(i)}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                  {data.target_audiences.length === 0 && (
                    <p className="text-xs text-muted-foreground">No audiences.</p>
                  )}
                </div>
              </section>

              {/* Campaigns */}
              <section className="py-4">
                <p className="mb-3 text-sm font-bold">Campaigns</p>
                {data.campaigns.map((c) => (
                  <div key={c} className="mb-2 flex items-center gap-2 rounded-lg border p-2">
                    <span className="flex-1 text-sm font-medium">{c}</span>
                    <button className="text-muted-foreground hover:text-destructive" onClick={() => delCampaign(c)}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
                {data.campaigns.length === 0 && (
                  <p className="text-xs text-muted-foreground">No campaigns.</p>
                )}
                <p className="mt-2 text-xs text-muted-foreground">
                  Deleting affects future posts only — already-reviewed/published posts are kept.
                </p>
              </section>
            </>
          )}
        </div>

        {/* footer */}
        <div className="flex items-center justify-end gap-3 border-t bg-muted/30 px-6 py-4 rounded-b-2xl">
          <span className="mr-auto text-xs text-muted-foreground">Saved as brand overrides, applied on re-plan.</span>
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="outline" size="sm" onClick={handleSave} disabled={saving || loading}>
            Save
          </Button>
          <Button size="sm" onClick={handleApply} disabled={saving || loading}>
            {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <RotateCcw className="mr-1.5 h-4 w-4" />}
            Apply &amp; re-plan
          </Button>
        </div>
      </div>
    </div>
  );
}
