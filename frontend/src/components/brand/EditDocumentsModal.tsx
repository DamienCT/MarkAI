"use client";

import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { X, Trash2, Plus, Loader2, RotateCcw, Wand2 } from "lucide-react";
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
type Audience = { name?: string; description?: string };
type Campaign = { name: string; description?: string };
type Theme = string | { month?: string; theme_name?: string; theme?: string; [k: string]: unknown };

interface OverridesData {
  cadence: Cadence;
  content_pillars: string[];
  target_audiences: Audience[];
  campaigns: Campaign[];
  removed_campaigns: string[];
  positioning: string;
  monthly_themes: Theme[];
  content_format: string;
  brand_voice: string;
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// "Month YYYY" labels for the next `count` months (incl. current).
function upcomingMonths(count = 18): string[] {
  const out: string[] = [];
  const d = new Date();
  d.setDate(1);
  for (let i = 0; i < count; i++) {
    out.push(`${MONTHS[d.getMonth()]} ${d.getFullYear()}`);
    d.setMonth(d.getMonth() + 1);
  }
  return out;
}

function themeLabel(t: Theme): { month: string; text: string } {
  if (typeof t === "string") return { month: "", text: t };
  return { month: t?.month || "", text: t?.theme_name || t?.theme || "" };
}

// Normalize a month label ("August 2026" or "2026-08") → "YYYY-MM" key.
function monthKey(label: string): string {
  const s = (label || "").trim();
  const dash = s.split("-");
  if (dash.length >= 2 && /^\d{4}$/.test(dash[0]) && /^\d{1,2}$/.test(dash[1])) {
    return `${dash[0]}-${dash[1].padStart(2, "0")}`;
  }
  let mo = -1, yr = -1;
  for (const t of s.replace(",", " ").split(/\s+/)) {
    const idx = MONTHS.findIndex((m) => m.toLowerCase().startsWith(t.toLowerCase()) && t.length >= 3);
    if (idx >= 0) mo = idx + 1;
    else if (/^\d{4}$/.test(t)) yr = parseInt(t, 10);
  }
  return mo > 0 && yr > 0 ? `${yr}-${String(mo).padStart(2, "0")}` : "";
}

// "2026-08" → "August 2026"
function labelFromKey(key: string): string {
  const [y, m] = key.split("-");
  const idx = parseInt(m, 10) - 1;
  return idx >= 0 && idx < 12 ? `${MONTHS[idx]} ${y}` : key;
}

// Themes are one-per-month for the year (a fixed set). Show a row for every
// month in the next 12 months UNION any month an existing theme already covers
// (so nothing is dropped), preserving rich theme objects and adding empty
// placeholders for gaps — the user edits e.g. "December 2026" directly.
function expandThemes(themes: Theme[]): Theme[] {
  const byKey: Record<string, Theme> = {};
  for (const t of themes) {
    const k = monthKey(themeLabel(t).month);
    if (k) byKey[k] = t;
  }
  const keys = new Set<string>(upcomingMonths(12).map(monthKey));
  Object.keys(byKey).forEach((k) => keys.add(k));
  return [...keys]
    .filter(Boolean)
    .sort()
    .map((k) => {
      const existing = byKey[k];
      if (existing) {
        return typeof existing === "string" ? { month: labelFromKey(k), theme_name: existing } : existing;
      }
      return { month: labelFromKey(k), theme_name: "" };
    });
}

// Map themes by month-key → text, to diff which months the user changed.
function themesByMonth(themes: Theme[]): Record<string, string> {
  const m: Record<string, string> = {};
  for (const t of themes) {
    const { month, text } = themeLabel(t);
    const k = monthKey(month);
    if (k) m[k] = text || "";
  }
  return m;
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
  const [refining, setRefining] = useState<number | null>(null);
  // Snapshot of the data as loaded, to diff which months the user changed.
  const initial = useRef<OverridesData | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .get<{
        cadence?: Cadence;
        content_pillars?: string[];
        target_audiences?: (string | Audience)[];
        campaigns?: (string | Campaign)[];
        removed_campaigns?: string[];
        positioning?: string;
        monthly_themes?: Theme[];
        content_format?: string;
        brand_voice?: string;
      }>(`/api/v1/brands/${brandId}/overrides`)
      .then((d) => {
        const loaded: OverridesData = {
          cadence: d.cadence || {},
          content_pillars: d.content_pillars || [],
          target_audiences: (d.target_audiences || []).map((a) =>
            typeof a === "string" ? { name: a, description: "" } : a
          ),
          campaigns: (d.campaigns || []).map((c) =>
            typeof c === "string" ? { name: c, description: "" } : c
          ),
          removed_campaigns: d.removed_campaigns || [],
          positioning: d.positioning || "",
          monthly_themes: expandThemes(d.monthly_themes || []),
          content_format: d.content_format || "posts_only",
          brand_voice: d.brand_voice || "",
        };
        initial.current = JSON.parse(JSON.stringify(loaded));
        setData(loaded);
      })
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

  const setAudienceName = (i: number, v: string) =>
    setData((d) => d && {
      ...d,
      target_audiences: d.target_audiences.map((a, j) => (j === i ? { ...a, name: v } : a)),
    });
  const delAudience = (i: number) =>
    setData((d) => d && { ...d, target_audiences: d.target_audiences.filter((_, j) => j !== i) });
  const addAudience = () =>
    setData((d) => d && { ...d, target_audiences: [...d.target_audiences, { name: "New audience", description: "" }] });

  const setCampaignField = (i: number, field: "name" | "description", v: string) =>
    setData((d) => d && {
      ...d,
      campaigns: d.campaigns.map((c, j) => (j === i ? { ...c, [field]: v } : c)),
    });
  const delCampaign = (i: number) =>
    setData((d) => {
      if (!d) return d;
      const name = d.campaigns[i]?.name;
      return {
        ...d,
        campaigns: d.campaigns.filter((_, j) => j !== i),
        removed_campaigns: name
          ? [...new Set([...d.removed_campaigns, name])]
          : d.removed_campaigns,
      };
    });
  const addCampaign = () =>
    setData((d) => d && { ...d, campaigns: [...d.campaigns, { name: "New campaign", description: "" }] });

  const setPositioning = (v: string) => setData((d) => d && { ...d, positioning: v });

  const setTheme = (i: number, v: string) =>
    setData((d) => d && {
      ...d,
      monthly_themes: d.monthly_themes.map((t, j) =>
        j === i ? (typeof t === "string" ? { month: "", theme_name: v } : { ...t, theme_name: v }) : t
      ),
    });

  // 🪄 AI: reformulate the user's rough theme text into a planning-ready theme.
  async function refineTheme(i: number) {
    if (!data) return;
    const { month, text } = themeLabel(data.monthly_themes[i]);
    if (!text.trim()) {
      toast.error("Write a rough theme first, then refine it");
      return;
    }
    setRefining(i);
    try {
      const res = await api.post<{ theme: string }>(
        `/api/v1/brands/${brandId}/themes/refine`,
        { text, month }
      );
      if (res?.theme) {
        setTheme(i, res.theme);
        toast.success("Theme refined");
      }
    } catch {
      toast.error("AI refinement failed");
    } finally {
      setRefining(null);
    }
  }

  const setFormat = (f: string) => setData((d) => d && { ...d, content_format: f });

  // ── persistence ───────────────────────────────────────────
  async function persist(): Promise<boolean> {
    if (!data) return false;
    const body = {
      cadence: data.cadence,
      content_pillars: data.content_pillars,
      target_audiences: data.target_audiences.filter((a) => (a.name || "").trim()),
      campaigns: data.campaigns.filter((c) => (c.name || "").trim()),
      positioning: data.positioning,
      // Only persist months that actually have a theme (drop empty placeholders).
      monthly_themes: data.monthly_themes.filter((t) => themeLabel(t).text.trim()),
      content_format: data.content_format,
      removed_campaigns: data.removed_campaigns,
    };
    await api.put(`/api/v1/brands/${brandId}/overrides`, body);
    return true;
  }

  // Which months to target on Apply. null = full re-plan (a global lever like
  // cadence/pillars/audiences/positioning/campaigns changed — affects every
  // month). Otherwise the "YYYY-MM" months whose theme text changed.
  function computeTargetMonths(): string[] | null {
    const init = initial.current;
    if (!init || !data) return null;
    const globals: (keyof OverridesData)[] = [
      "cadence", "content_pillars", "target_audiences",
      "campaigns", "removed_campaigns", "positioning", "content_format",
    ];
    const globalChanged = globals.some(
      (f) => JSON.stringify(init[f]) !== JSON.stringify(data[f])
    );
    if (globalChanged) return null;
    const a = themesByMonth(init.monthly_themes);
    const b = themesByMonth(data.monthly_themes);
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    const changed: string[] = [];
    keys.forEach((k) => {
      if ((a[k] || "") !== (b[k] || "")) changed.push(k);
    });
    return changed;
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
      const target = computeTargetMonths();
      await persist();
      const body = target && target.length ? { months: target } : {};
      await api.post(`/api/v1/brands/${brandId}/overrides/apply`, body);
      if (target && target.length) {
        toast.success(
          `Re-planning ${target.length} month${target.length > 1 ? "s" : ""} you changed — the calendar will update shortly`
        );
      } else {
        toast.success("Re-planning all months — the calendar will update shortly");
      }
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
                      <input
                        className="flex-1 bg-transparent text-sm outline-none"
                        value={a.name || ""}
                        placeholder="Audience name"
                        onChange={(e) => setAudienceName(i, e.target.value)}
                      />
                      <button className="text-muted-foreground hover:text-destructive" onClick={() => delAudience(i)}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                  <button
                    className="mt-1 w-full rounded-lg border border-dashed border-primary/40 py-2 text-xs font-bold text-primary hover:bg-primary/5"
                    onClick={addAudience}
                  >
                    <Plus className="mr-1 inline h-3.5 w-3.5" /> Add audience
                  </button>
                </div>
              </section>

              {/* Positioning */}
              <section className="border-b py-4">
                <p className="mb-3 text-sm font-bold">Positioning</p>
                <textarea
                  className="min-h-[80px] w-full rounded-lg border bg-transparent p-2.5 text-sm outline-none focus:border-primary"
                  value={data.positioning}
                  placeholder="How the brand is positioned vs. competitors (one or two sentences)…"
                  onChange={(e) => setPositioning(e.target.value)}
                />
              </section>

              {/* Monthly themes — one per month (fixed). Edit the text, or use
                  the wand to let AI reformulate your note into a clean theme. */}
              <section className="border-b py-4">
                <p className="mb-1 text-sm font-bold">Monthly themes</p>
                <p className="mb-3 text-xs text-muted-foreground">
                  One theme per month. Write your idea on the right month, then hit 🪄 to let AI polish it.
                </p>
                {data.monthly_themes.map((t, i) => {
                  const { month, text } = themeLabel(t);
                  return (
                    <div key={i} className="mb-2 flex items-center gap-2 rounded-lg border p-2">
                      <span className="shrink-0 w-24 text-xs font-semibold text-muted-foreground">
                        {month || "—"}
                      </span>
                      <input
                        className="flex-1 bg-transparent text-sm outline-none"
                        value={text}
                        placeholder="Theme for this month…"
                        onChange={(e) => setTheme(i, e.target.value)}
                      />
                      <button
                        type="button"
                        title="Reformulate with AI"
                        className="shrink-0 rounded-md p-1 text-primary hover:bg-primary/10 disabled:opacity-40"
                        disabled={refining !== null || !text.trim()}
                        onClick={() => refineTheme(i)}
                      >
                        {refining === i ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Wand2 className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  );
                })}
              </section>

              {/* Campaigns */}
              <section className="py-4">
                <p className="mb-3 text-sm font-bold">Campaigns</p>
                {data.campaigns.map((c, i) => (
                  <div key={i} className="mb-2 flex items-start gap-2 rounded-lg border p-2">
                    <div className="flex-1 space-y-1.5">
                      <input
                        className="w-full bg-transparent text-sm font-medium outline-none"
                        value={c.name}
                        placeholder="Campaign name"
                        onChange={(e) => setCampaignField(i, "name", e.target.value)}
                      />
                      <input
                        className="w-full bg-transparent text-xs text-muted-foreground outline-none"
                        value={c.description || ""}
                        placeholder="Short description"
                        onChange={(e) => setCampaignField(i, "description", e.target.value)}
                      />
                    </div>
                    <button className="mt-0.5 text-muted-foreground hover:text-destructive" onClick={() => delCampaign(i)}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
                {data.campaigns.length === 0 && (
                  <p className="mb-2 text-xs text-muted-foreground">No campaigns.</p>
                )}
                <button
                  className="mt-1 w-full rounded-lg border border-dashed border-primary/40 py-2 text-xs font-bold text-primary hover:bg-primary/5"
                  onClick={addCampaign}
                >
                  <Plus className="mr-1 inline h-3.5 w-3.5" /> Add campaign
                </button>
              </section>
            </>
          )}
        </div>

        {/* footer */}
        <div className="flex items-center justify-end gap-3 border-t bg-muted/30 px-6 py-4 rounded-b-2xl">
          <span className="mr-auto text-xs text-muted-foreground">
            Saved as brand overrides, applied on Apply.
          </span>
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button variant="outline" size="sm" onClick={handleSave} disabled={saving || loading}>
            Save
          </Button>
          <Button size="sm" onClick={handleApply} disabled={saving || loading}>
            {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <RotateCcw className="mr-1.5 h-4 w-4" />}
            Apply
          </Button>
        </div>
      </div>
    </div>
  );
}
