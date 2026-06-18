"use client";

import React, { useEffect, useState, useMemo } from "react";
import { useParams, useRouter, useSearchParams, usePathname } from "next/navigation";
import { toast } from "sonner";
import { ArrowLeft, CheckSquare, Trash2, X, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { format } from "date-fns";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { STATUS_COLORS, CHANNEL_COLORS, CHANNEL_DISPLAY_NAMES } from "@/lib/constants";
import { WorkingStageTracker } from "@/components/content/WorkingStageTracker";
import { useOpenedContent } from "@/lib/opened-content";
import type { CalendarItem, Brand } from "@/types";

const DATE_FILTERS: { value: string; label: string; days: number | null }[] = [
  { value: "all", label: "All time", days: null },
  { value: "today", label: "Today", days: 1 },
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "30d", label: "Last 30 days", days: 30 },
  { value: "90d", label: "Last 90 days", days: 90 },
];

const STATUS_LABELS: Record<string, string> = {
  planned: "Planned",
  queued: "Queued",
  working: "Working",
  in_review: "In Review",
  reworking: "Reworking",
  approved: "Approved",
  scheduled: "Scheduled",
  publishing: "Publishing",
  published: "Published",
  failed: "Failed",
};

const CHANNEL_DISPLAY = CHANNEL_DISPLAY_NAMES;

export default function StagePage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const status = params.status as string;

  const [items, setItems] = useState<CalendarItem[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(true);
  const [brandFilter, setBrandFilter] = useState<string>("all");
  const [channelFilter, setChannelFilter] = useState<string>("all");
  const [dateFilter, setDateFilter] = useState<string>("all");
  // In Review only: filter by exact PUBLISH date (calendar_item.scheduled_at),
  // not the generation/created date. Empty = all dates. Initialized from the URL
  // (?date=YYYY-MM-DD) so it survives navigating into a post and back.
  const [publishDateFilter, setPublishDateFilter] = useState<string>(
    () => searchParams.get("date") || ""
  );

  // Mirror the publish-date filter into the URL so router.back() from a post
  // restores it (the page re-mounts and re-reads it from the query string).
  useEffect(() => {
    const sp = new URLSearchParams(Array.from(searchParams.entries()));
    if (publishDateFilter) sp.set("date", publishDateFilter);
    else sp.delete("date");
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [publishDateFilter]);
  // "all" | "system" | "manual". Items whose `theme` is populated come from
  // the planning agent (it sets theme + weekly_sub_theme); manual New Content
  // creations leave theme null.
  const [originFilter, setOriginFilter] = useState<string>("all");
  const { isOpened } = useOpenedContent();

  // Bulk selection + delete (so users don't have to open each card to delete).
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
  };

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`Delete ${selectedIds.size} item${selectedIds.size !== 1 ? "s" : ""}? This cannot be undone.`)) {
      return;
    }
    setDeleting(true);
    const ids = Array.from(selectedIds);
    try {
      const results = await Promise.allSettled(
        ids.map((id) => api.delete(`/api/v1/calendar/${id}`))
      );
      const failed = results.filter((r) => r.status === "rejected").length;
      const ok = ids.filter((_, i) => results[i].status === "fulfilled");
      setItems((prev) => prev.filter((i) => !ok.includes(i.id)));
      exitSelectMode();
      if (failed > 0) toast.error(`${failed} item${failed !== 1 ? "s" : ""} could not be deleted`);
      else toast.success(`Deleted ${ok.length} item${ok.length !== 1 ? "s" : ""}`);
    } finally {
      setDeleting(false);
    }
  };

  useEffect(() => {
    async function fetchData() {
      try {
        const [calItems, brandList] = await Promise.allSettled([
          api.get<CalendarItem[]>("/api/v1/calendar", { status_filter: status }),
          api.get<Brand[]>("/api/v1/brands"),
        ]);
        if (calItems.status === "fulfilled") setItems(calItems.value);
        if (brandList.status === "fulfilled") setBrands(brandList.value);
      } catch {
        // Errors are optional
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [status]);

  const channels = useMemo(() => {
    const set = new Set<string>();
    items.forEach(i => { if (i.channel) set.add(i.channel); });
    return Array.from(set).sort();
  }, [items]);

  const filtered = useMemo(() => {
    const dateCfg = DATE_FILTERS.find((d) => d.value === dateFilter);
    const cutoff = dateCfg?.days != null ? Date.now() - dateCfg.days * 86_400_000 : null;
    const result = items.filter(i => {
      if (brandFilter !== "all" && i.brand_id !== brandFilter) return false;
      if (channelFilter !== "all" && i.channel !== channelFilter) return false;
      if (cutoff !== null) {
        if (!i.created_at) return false;
        if (new Date(i.created_at).getTime() < cutoff) return false;
      }
      if (originFilter !== "all") {
        const fromSystem = !!(i.theme && i.theme.trim());
        if (originFilter === "system" && !fromSystem) return false;
        if (originFilter === "manual" && fromSystem) return false;
      }
      if (status === "in_review" && publishDateFilter) {
        if (!i.scheduled_at) return false;
        if (format(new Date(i.scheduled_at), "yyyy-MM-dd") !== publishDateFilter) return false;
      }
      return true;
    });

    // In Review: order by posting date ascending so the soonest scheduled_at
    // sits first (top-left) and the grid flows 16 Jun → 17 Jun → 18 Jun left to
    // right. Items without a posting date go last.
    if (status === "in_review") {
      result.sort((a, b) => {
        const ta = a.scheduled_at ? new Date(a.scheduled_at).getTime() : Infinity;
        const tb = b.scheduled_at ? new Date(b.scheduled_at).getTime() : Infinity;
        return ta - tb;
      });
    }
    return result;
  }, [items, brandFilter, channelFilter, dateFilter, originFilter, status, publishDateFilter]);

  const label = STATUS_LABELS[status] || status;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push("/content")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold">{label}</h1>
              <Badge className={STATUS_COLORS[status] || ""}>{filtered.length} item{filtered.length !== 1 ? "s" : ""}</Badge>
            </div>
            <p className="text-sm text-muted-foreground mt-0.5">Content in the {label.toLowerCase()} stage</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {selectMode ? (
            <>
              <Button
                variant="outline"
                size="sm"
                disabled={filtered.length === 0 || deleting}
                onClick={() =>
                  setSelectedIds((prev) => {
                    const next = new Set(prev);
                    const allSel =
                      filtered.length > 0 && filtered.every((i) => prev.has(i.id));
                    if (allSel) filtered.forEach((i) => next.delete(i.id));
                    else filtered.forEach((i) => next.add(i.id));
                    return next;
                  })
                }
              >
                <CheckSquare className="mr-1.5 h-4 w-4" />
                {filtered.length > 0 && filtered.every((i) => selectedIds.has(i.id))
                  ? "Deselect all"
                  : "Select all"}
              </Button>
              <span className="text-sm text-muted-foreground">
                {selectedIds.size} selected
              </span>
              <Button
                variant="destructive"
                size="sm"
                disabled={selectedIds.size === 0 || deleting}
                onClick={handleBulkDelete}
              >
                {deleting ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="mr-1.5 h-4 w-4" />
                )}
                Delete
              </Button>
              <Button variant="ghost" size="sm" onClick={exitSelectMode} disabled={deleting}>
                <X className="mr-1.5 h-4 w-4" />
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" size="sm" onClick={() => setSelectMode(true)}>
                <CheckSquare className="mr-1.5 h-4 w-4" />
                Select
              </Button>
              {status !== "in_review" && (
                <Select value={brandFilter} onValueChange={setBrandFilter}>
                  <SelectTrigger className="w-[160px]">
                    <SelectValue placeholder="All Brands" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Brands</SelectItem>
                    {brands.map(b => (
                      <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <Select value={channelFilter} onValueChange={setChannelFilter}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="All Channels" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Channels</SelectItem>
                  {channels.map(ch => (
                    <SelectItem key={ch} value={ch}>{CHANNEL_DISPLAY[ch] || ch}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {status === "in_review" ? (
                <div className="flex items-center gap-1">
                  <Input
                    type="date"
                    value={publishDateFilter}
                    onChange={(e) => setPublishDateFilter(e.target.value)}
                    className="w-[170px]"
                    aria-label="Filter by publish date"
                  />
                  {publishDateFilter && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-9 w-9 p-0"
                      onClick={() => setPublishDateFilter("")}
                      aria-label="Clear date filter"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ) : status !== "working" && (
                <Select value={dateFilter} onValueChange={setDateFilter}>
                  <SelectTrigger className="w-[150px]" aria-label="Filter by generation date">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DATE_FILTERS.map(d => (
                      <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {status === "in_review" && (
                <Select value={originFilter} onValueChange={setOriginFilter}>
                  <SelectTrigger className="w-[140px]" aria-label="Filter by origin">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Origins</SelectItem>
                    <SelectItem value="system">System</SelectItem>
                    <SelectItem value="manual">Manual</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </>
          )}
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-lg text-muted-foreground">No content in this stage</p>
          <Button variant="outline" className="mt-4" onClick={() => router.push("/content")}>
            Back to Content Studio
          </Button>
        </div>
      ) : (
        <div className="space-y-6">
          {status === "working" && (
            <WorkingStageTracker items={filtered} pollInterval={5000} />
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3">
          {filtered.map(item => {
            const selected = selectedIds.has(item.id);
            return (
            <div
              key={item.id}
              onClick={() =>
                selectMode ? toggleSelect(item.id) : router.push(`/content/${item.id}`)
              }
              className="cursor-pointer"
            >
              <Card className={`relative p-4 h-full transition-shadow ${
                selectMode && selected
                  ? "ring-2 ring-primary shadow-md"
                  : "hover:shadow-md"
              }`}>
                {selectMode && (
                  <input
                    type="checkbox"
                    className="absolute right-3 top-3 h-4 w-4"
                    checked={selected}
                    readOnly
                    aria-label="Select item"
                  />
                )}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <p className={`text-sm font-medium line-clamp-2 flex-1 ${selectMode ? "pr-6" : ""}`}>{item.title || "Untitled"}</p>
                  {!selectMode && (
                    <div className="flex items-center gap-1 shrink-0">
                      {!isOpened(item.id) && (
                        <span className="inline-flex items-center rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 leading-none">
                          New
                        </span>
                      )}
                      <Badge variant="outline" className={`text-[10px] ${CHANNEL_COLORS[item.channel] || ""}`}>
                        {CHANNEL_DISPLAY[item.channel] || item.channel}
                      </Badge>
                    </div>
                  )}
                </div>
                {item.description && (
                  <p className="text-xs text-muted-foreground line-clamp-2 mb-2">{item.description}</p>
                )}
                <div className="flex items-center gap-2 flex-wrap">
                  {item.pillar && (
                    <Badge variant="secondary" className="text-[10px] bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300">
                      {item.pillar}
                    </Badge>
                  )}
                  {item.target_audience && (
                    <Badge variant="secondary" className="text-[10px] bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-300">
                      {item.target_audience}
                    </Badge>
                  )}
                </div>
                {item.scheduled_at && (
                  <p className="text-[10px] text-muted-foreground mt-2">{formatDateTime(item.scheduled_at)}</p>
                )}
                {item.brand_name && (
                  <p className="text-[10px] text-muted-foreground mt-1">{item.brand_name}</p>
                )}
              </Card>
            </div>
            );
          })}
        </div>
        </div>
      )}
    </div>
  );
}
