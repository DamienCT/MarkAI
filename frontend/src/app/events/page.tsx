"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { format, parseISO } from "date-fns";
import { toast } from "sonner";
import {
  CalendarHeart,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EventDialog } from "@/components/events/EventDialog";
import { DetectEventsDialog } from "@/components/events/DetectEventsDialog";
import { api } from "@/lib/api";
import { getStoredBrandValue } from "@/lib/brand-selection";
import type { Brand, Event } from "@/types";

const SCOPE_ALL = "all";
const SCOPE_GLOBAL = "global";
const CATEGORY_ALL = "__all__";

const CATEGORIES = [
  { value: "holiday", label: "Holiday" },
  { value: "awareness", label: "Awareness" },
  { value: "industry", label: "Industry" },
  { value: "local", label: "Local" },
  { value: "custom", label: "Custom" },
];

function formatDateRange(start: string, end: string | null): string {
  const startFmt = format(parseISO(start), "d MMM yyyy");
  if (!end || end === start) return startFmt;
  const endFmt = format(parseISO(end), "d MMM yyyy");
  return `${startFmt} — ${endFmt}`;
}

function categoryColor(c: string | null): string {
  switch (c) {
    case "holiday":
      return "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200";
    case "awareness":
      return "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200";
    case "industry":
      return "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200";
    case "local":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200";
    default:
      return "bg-muted text-muted-foreground";
  }
}

export default function EventsPage() {
  const [events, setEvents] = useState<Event[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [scope, setScope] = useState<string>(SCOPE_ALL);
  const [categoryFilter, setCategoryFilter] = useState<string>(CATEGORY_ALL);
  const [upcomingOnly, setUpcomingOnly] = useState<boolean>(false);

  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<Event | null>(null);
  const [detectOpen, setDetectOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Event | null>(null);

  const brandNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const b of brands) m.set(b.id, b.name);
    return m;
  }, [brands]);

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | boolean> = { scope };
      if (categoryFilter !== CATEGORY_ALL) params.category = categoryFilter;
      if (upcomingOnly) params.upcoming_only = true;
      const data = await api.get<Event[]>("/api/v1/events", params);
      setEvents(data);
    } catch {
      setError("Failed to load events");
    } finally {
      setLoading(false);
    }
  }, [scope, categoryFilter, upcomingOnly]);

  // Follow the global sidebar brand selection: hydrate from localStorage after
  // mount (client-only, avoids SSR mismatch) and update when it changes. The
  // stored value ("all" or a brand uuid) is a valid `scope`; a brand scope
  // includes that brand's events plus global ones. The local scope dropdown
  // still works; the global selection wins when the event fires.
  useEffect(() => {
    setScope(getStoredBrandValue());
    // `Event` is shadowed by our domain type import — qualify the DOM one.
    const handler = (e: globalThis.Event) => {
      const brandId = (e as CustomEvent).detail?.brandId;
      setScope(brandId || SCOPE_ALL);
    };
    window.addEventListener("brand-changed", handler);
    return () => window.removeEventListener("brand-changed", handler);
  }, []);

  useEffect(() => {
    async function fetchBrands() {
      try {
        const data = await api.get<Brand[]>("/api/v1/brands");
        setBrands(data);
      } catch {
        // non-fatal
      }
    }
    fetchBrands();
  }, []);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await api.delete<void>(`/api/v1/events/${deleteTarget.id}`);
      toast.success("Event deleted");
      setDeleteTarget(null);
      fetchEvents();
    } catch (err: unknown) {
      const msg =
        (err as { detail?: string })?.detail ??
        (err instanceof Error ? err.message : "Failed to delete event");
      toast.error(msg);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <CalendarHeart className="h-7 w-7" />
            Events
          </h1>
          <p className="text-muted-foreground">
            Significant days that shape your marketing plan. Edit here, then
            rerun research for each brand to pick up the changes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => setDetectOpen(true)}
          >
            <Sparkles className="mr-2 h-4 w-4" />
            Detect Events
          </Button>
          <Button
            onClick={() => {
              setEditing(null);
              setEditOpen(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Event
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="min-w-[200px]">
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger>
              <SelectValue placeholder="Scope" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={SCOPE_ALL}>All scopes</SelectItem>
              <SelectItem value={SCOPE_GLOBAL}>Global only</SelectItem>
              {brands.map((b) => (
                <SelectItem key={b.id} value={b.id}>
                  {b.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="min-w-[180px]">
          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger>
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={CATEGORY_ALL}>All categories</SelectItem>
              {CATEGORIES.map((c) => (
                <SelectItem key={c.value} value={c.value}>
                  {c.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant={upcomingOnly ? "default" : "outline"}
          size="sm"
          onClick={() => setUpcomingOnly((v) => !v)}
        >
          Upcoming only
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchEvents}
          title="Refresh"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      <div className="rounded-md border bg-card">
        {loading ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : error ? (
          <div className="p-8 text-center">
            <p className="text-muted-foreground">{error}</p>
            <Button variant="outline" className="mt-3" onClick={fetchEvents}>
              Retry
            </Button>
          </div>
        ) : events.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-lg text-muted-foreground">No events yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Click &ldquo;Detect Events&rdquo; to auto-populate, or add
              entries manually.
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Scope</TableHead>
                <TableHead>Annual</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((ev) => (
                <TableRow key={ev.id}>
                  <TableCell>
                    <div className="font-medium">{ev.title}</div>
                    {ev.description && (
                      <div className="text-xs text-muted-foreground line-clamp-1">
                        {ev.description}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatDateRange(ev.start_date, ev.end_date)}
                  </TableCell>
                  <TableCell>
                    {ev.category ? (
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${categoryColor(ev.category)}`}
                      >
                        {ev.category}
                      </span>
                    ) : (
                      <span className="text-muted-foreground text-xs">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {ev.brand_id ? (
                      <Badge variant="outline">
                        {brandNameById.get(ev.brand_id) ?? "Brand"}
                      </Badge>
                    ) : (
                      <Badge variant="secondary">Global</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {ev.is_annual ? (
                      <Badge variant="outline">Annual</Badge>
                    ) : (
                      <span className="text-muted-foreground text-xs">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground">
                      {ev.source === "ai_detected" ? "AI detected" : "Manual"}
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => {
                          setEditing(ev);
                          setEditOpen(true);
                        }}
                        aria-label="Edit event"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeleteTarget(ev)}
                        aria-label="Delete event"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <EventDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        brands={brands}
        event={editing}
        onSaved={fetchEvents}
      />

      <DetectEventsDialog
        open={detectOpen}
        onOpenChange={setDetectOpen}
        brands={brands}
        onDetected={fetchEvents}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title="Delete event?"
        description={
          deleteTarget
            ? `"${deleteTarget.title}" will be removed. This cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={handleDelete}
      />
    </div>
  );
}
