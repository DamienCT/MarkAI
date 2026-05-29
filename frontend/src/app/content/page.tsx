"use client";

import React, { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { toast } from "sonner";
import { Plus, LayoutGrid, List } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { KanbanBoard } from "@/components/content/KanbanBoard";
import { ContentCard } from "@/components/content/ContentCard";
import { api } from "@/lib/api";
import { getStoredBrandId } from "@/lib/brand-selection";
import { useRequireRole } from "@/lib/hooks";
import type { CalendarItem, Brand, Channel } from "@/types";
import { ALL_CHANNELS, CHANNEL_DISPLAY_NAMES } from "@/types";

interface BrandChannelConfig {
  channels?: Record<string, { enabled?: boolean }>;
}

// Date filter options (filters by calendar_item.created_at — i.e. when the
// post entered the pipeline, which is what the UI calls "generation date").
const DATE_FILTERS: { value: string; label: string; days: number | null }[] = [
  { value: "all", label: "All time", days: null },
  { value: "today", label: "Today", days: 1 },
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "30d", label: "Last 30 days", days: 30 },
  { value: "90d", label: "Last 90 days", days: 90 },
];

export default function ContentStudioPage() {
  const { hasAccess, loading: roleLoading } = useRequireRole("editor");
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"kanban" | "grid">("kanban");
  const [dateFilter, setDateFilter] = useState<string>("all");

  // Apply the date-range filter on the client. We filter by created_at —
  // the field that closest tracks "when this post was generated/queued".
  const filteredItems = useMemo(() => {
    const cfg = DATE_FILTERS.find((d) => d.value === dateFilter);
    if (!cfg || cfg.days === null) return items;
    const cutoff = Date.now() - cfg.days * 24 * 60 * 60 * 1000;
    return items.filter((i) => {
      if (!i.created_at) return false;
      return new Date(i.created_at).getTime() >= cutoff;
    });
  }, [items, dateFilter]);

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [submitting, setSubmitting] = useState(false);

  // Form state
  const [formBrandId, setFormBrandId] = useState("");
  const [formChannels, setFormChannels] = useState<Channel[]>([]);
  const [formTitle, setFormTitle] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formScheduledAt, setFormScheduledAt] = useState("");

  // Available channels for the selected brand
  const [availableChannels, setAvailableChannels] = useState<Channel[]>(ALL_CHANNELS);

  // AbortController ref to cancel in-flight requests on brand switch / unmount
  const abortRef = useRef<AbortController | null>(null);

  const fetchItems = useCallback(async (brandId?: string | null) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    setLoading(true);
    try {
      const params: Record<string, string | number> = {};
      if (brandId) params.brand_id = brandId;
      const data = await api.get<CalendarItem[]>("/api/v1/calendar", params, { signal });
      const allItems = Array.isArray(data) ? data : [];
      // Filter queued/planned items to next 7 days only — other statuses show regardless
      const now = new Date();
      const horizon = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
      const filtered = allItems.filter((item) => {
        if (item.status === "queued" || item.status === "planned") {
          if (!item.scheduled_at) return false;
          const d = new Date(item.scheduled_at);
          return d >= now && d <= horizon;
        }
        return true; // Show all other statuses (working, in_review, scheduled, etc.)
      });
      setItems(filtered);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setItems([]);
      toast.error("Failed to load content items");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems(getStoredBrandId());
    // Fetch brands for the dialog
    api.get<Brand[]>("/api/v1/brands").then((d) => setBrands(Array.isArray(d) ? d : [])).catch(() => {
      toast.error("Failed to load brands");
    });

    const handler = (e: Event) => {
      const brandId = (e as CustomEvent).detail?.brandId;
      fetchItems(brandId);
    };
    window.addEventListener("brand-changed", handler);
    return () => {
      window.removeEventListener("brand-changed", handler);
      abortRef.current?.abort();
    };
  }, [fetchItems]);

  // When brand selection changes in the form, update available channels
  useEffect(() => {
    if (!formBrandId) {
      setAvailableChannels(ALL_CHANNELS);
      return;
    }
    const brand = brands.find((b) => b.id === formBrandId);
    if (brand) {
      // Try to get channels from brand_guidelines or social_accounts
      const brandConfig = brand.brand_guidelines as BrandChannelConfig | undefined;
      if (brandConfig?.channels) {
        const enabled = Object.entries(brandConfig.channels)
          .filter(([, cfg]) => cfg?.enabled)
          .map(([ch]) => ch as Channel)
          .filter((ch) => ALL_CHANNELS.includes(ch));
        if (enabled.length > 0) {
          setAvailableChannels(enabled);
          setFormChannels((prev) => prev.filter((c) => enabled.includes(c)));
          return;
        }
      }
      // Fallback: if brand has social_accounts, use those platforms
      if (brand.social_accounts && brand.social_accounts.length > 0) {
        const platforms = brand.social_accounts
          .map((sa) => sa.platform as Channel)
          .filter((p) => ALL_CHANNELS.includes(p));
        if (platforms.length > 0) {
          setAvailableChannels(platforms);
          setFormChannels((prev) => prev.filter((c) => platforms.includes(c)));
          return;
        }
      }
      setAvailableChannels(ALL_CHANNELS);
    }
  }, [formBrandId, brands]);

  const handleStatusChange = async (itemId: string, newStatus: string) => {
    try {
      await api.patch(`/api/v1/calendar/${itemId}`, { status: newStatus });
      setItems((prev) =>
        prev.map((item) =>
          item.id === itemId ? { ...item, status: newStatus } : item
        )
      );
      toast.success(`Status updated to ${newStatus}`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update status";
      toast.error(detail);
    }
  };

  const toggleChannel = (channel: Channel) => {
    setFormChannels((prev) =>
      prev.includes(channel)
        ? prev.filter((c) => c !== channel)
        : [...prev, channel]
    );
  };

  const resetForm = () => {
    setFormBrandId("");
    setFormChannels([]);
    setFormTitle("");
    setFormDescription("");
    setFormScheduledAt("");
  };

  const handleCreateContent = async () => {
    if (!formBrandId) {
      toast.error("Please select a brand");
      return;
    }
    if (!formTitle.trim()) {
      toast.error("Title is required");
      return;
    }
    if (formChannels.length === 0) {
      toast.error("Please select at least one channel");
      return;
    }

    setSubmitting(true);
    try {
      // Create one calendar item per channel
      const promises = formChannels.map((channel) =>
        api.post<CalendarItem>("/api/v1/calendar", {
          brand_id: formBrandId,
          channel,
          item_type: "post",
          title: formTitle.trim(),
          description: formDescription.trim() || null,
          scheduled_at: formScheduledAt || null,
          status: "queued",
        })
      );
      await Promise.all(promises);
      toast.success(
        formChannels.length === 1
          ? "Content created successfully"
          : `${formChannels.length} content items created`
      );
      setDialogOpen(false);
      resetForm();
      fetchItems(getStoredBrandId());
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to create content";
      toast.error(detail);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold">Content Studio</h1>
          <p className="text-muted-foreground">Create, manage, and schedule content</p>
        </div>
        <div className="flex gap-2 items-center">
          <Select value={dateFilter} onValueChange={setDateFilter}>
            <SelectTrigger className="w-[150px]" aria-label="Filter by generation date">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DATE_FILTERS.map((d) => (
                <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex rounded-md border">
            <Button
              variant={view === "kanban" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("kanban")}
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
            <Button
              variant={view === "grid" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("grid")}
            >
              <List className="h-4 w-4" />
            </Button>
          </div>
          <Button onClick={() => setDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New Content
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-[500px] w-full" />
        </div>
      ) : view === "kanban" ? (
        <KanbanBoard items={filteredItems} onStatusChange={handleStatusChange} />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filteredItems.length === 0 ? (
            <div className="col-span-full text-center py-12">
              <p className="text-lg font-medium text-muted-foreground">No content yet</p>
              <p className="text-sm text-muted-foreground mt-1">Create your first piece of content to get started</p>
            </div>
          ) : (
            filteredItems.map((item) => <ContentCard key={item.id} item={item} />)
          )}
        </div>
      )}

      {/* New Content Dialog */}
      <Dialog open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) resetForm(); }}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>Create New Content</DialogTitle>
            <DialogDescription>Add a new content item to your calendar.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {/* Brand */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Brand *</label>
              <Select value={formBrandId} onValueChange={setFormBrandId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a brand" />
                </SelectTrigger>
                <SelectContent>
                  {brands.map((b) => (
                    <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Channels (multi-select via toggle buttons) */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Channels *</label>
              <div className="flex flex-wrap gap-2">
                {availableChannels.map((ch) => (
                  <Button
                    key={ch}
                    type="button"
                    size="sm"
                    variant={formChannels.includes(ch) ? "default" : "outline"}
                    onClick={() => toggleChannel(ch)}
                  >
                    {CHANNEL_DISPLAY_NAMES[ch]}
                  </Button>
                ))}
              </div>
              {formChannels.length > 1 && (
                <p className="text-xs text-muted-foreground">
                  {formChannels.length} channels selected - one item per channel will be created.
                </p>
              )}
            </div>

            {/* Title */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Title *</label>
              <Input
                placeholder="Content title"
                value={formTitle}
                onChange={(e) => setFormTitle(e.target.value)}
              />
            </div>

            {/* Description */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Textarea
                placeholder="Optional description"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                rows={3}
              />
            </div>

            {/* Scheduled Date */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Scheduled Date</label>
              <Input
                type="datetime-local"
                value={formScheduledAt}
                onChange={(e) => setFormScheduledAt(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setDialogOpen(false); resetForm(); }}>
              Cancel
            </Button>
            <Button onClick={handleCreateContent} disabled={submitting}>
              {submitting ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
