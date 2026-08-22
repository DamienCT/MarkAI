"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowLeft, Plus, LayoutGrid, List } from "lucide-react";
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
import { api, isAuthError } from "@/lib/api";
import { getStoredBrandId } from "@/lib/brand-selection";
import { useRequireRole } from "@/lib/hooks";
import { watchPost } from "@/lib/post-watch";
import { toApiDatetime } from "@/lib/utils";
import type { CalendarItem, Brand, Channel } from "@/types";
import { ALL_CHANNELS, CHANNEL_DISPLAY_NAMES } from "@/types";

interface BrandChannelConfig {
  channels?: Record<string, { enabled?: boolean }>;
}

export default function ContentStudioPage() {
  useRequireRole("editor"); // redirects unauthorized users as a side effect
  const [items, setItems] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"kanban" | "grid">("kanban");

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [cameFromTrend, setCameFromTrend] = useState(false);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [submitting, setSubmitting] = useState(false);

  // Form state
  const [formBrandId, setFormBrandId] = useState("");
  const [formChannels, setFormChannels] = useState<Channel[]>([]);
  const [formItemType, setFormItemType] = useState<"post" | "reel">("post");
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
      // Queued/planned items appear in the kanban when:
      //  - they have NO scheduled_at (user can create posts without a date), OR
      //  - they ARE scheduled within the next 7 days
      // Other statuses (working, in_review, scheduled, etc.) always show.
      const now = new Date();
      const horizon = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
      const filtered = allItems.filter((item) => {
        if (item.status === "queued" || item.status === "planned") {
          if (!item.scheduled_at) return true;
          const d = new Date(item.scheduled_at);
          return d >= now && d <= horizon;
        }
        return true;
      });
      setItems(filtered);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      // Session expiry mid-load: the client is already redirecting to
      // sign-in — an error toast here would be a lie flashing over it.
      if (isAuthError(err)) return;
      setItems([]);
      toast.error("Failed to load content items");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems(getStoredBrandId());
    // Fetch brands for the dialog
    api.get<Brand[]>("/api/v1/brands").then((d) => setBrands(Array.isArray(d) ? d : [])).catch((err) => {
      if (isAuthError(err)) return; // redirect to sign-in already underway
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

  // Open the New Content dialog pre-filled when arriving from a trend card
  // (or any other "Create post about X" CTA). Reads ?brand_id&title&description
  // from the URL, opens the dialog, then clears the params.
  const searchParams = useSearchParams();
  const router = useRouter();
  useEffect(() => {
    const brandIdParam = searchParams.get("brand_id");
    const titleParam = searchParams.get("title");
    const descriptionParam = searchParams.get("description");
    const originParam = searchParams.get("origin");
    if (!brandIdParam && !titleParam && !descriptionParam) return;

    if (brandIdParam) setFormBrandId(brandIdParam);
    if (titleParam) setFormTitle(titleParam);
    if (descriptionParam) setFormDescription(descriptionParam);
    setDialogOpen(true);
    // Track that the dialog was opened from a trend card so closing it
    // (X, Cancel, ESC, click-outside) returns the user to /intelligence.
    if (originParam === "trend") setCameFromTrend(true);

    // Strip the params so a refresh doesn't re-open the dialog
    router.replace("/content", { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    setFormItemType("post");
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
          item_type: formItemType,
          title: formTitle.trim(),
          description: formDescription.trim() || null,
          scheduled_at: toApiDatetime(formScheduledAt) || null,
          status: "queued",
        })
      );
      const createdItems = await Promise.all(promises);

      // Hand off to the global post-watch toaster (mounted in
      // providers-wrapper) — it polls every 5s from anywhere in the app
      // and fires a green toast when each post finishes generation.
      for (const it of createdItems) {
        watchPost(
          it.id,
          it.title || formTitle.trim() || "Untitled",
          it.channel
        );
      }

      toast.success(
        formChannels.length === 1
          ? "Content created — we will notify you when it's ready"
          : `${formChannels.length} content items created — we will notify you when each is ready`
      );
      // After a successful submit, stay in Content Studio to let the user
      // see the new card. The "back to intelligence" auto-nav only fires
      // on actual cancel/close, not on submit.
      setCameFromTrend(false);
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
        <KanbanBoard items={items} />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.length === 0 ? (
            <div className="col-span-full text-center py-12">
              <p className="text-lg font-medium text-muted-foreground">No content yet</p>
              <p className="text-sm text-muted-foreground mt-1">Create your first piece of content to get started</p>
            </div>
          ) : (
            items.map((item) => <ContentCard key={item.id} item={item} />)
          )}
        </div>
      )}

      {/* New Content Dialog */}
      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) {
            resetForm();
            // When the dialog was opened from a trend card, closing it
            // (X / Cancel / ESC / click-outside) sends the user back to
            // the Intelligence page where they came from.
            if (cameFromTrend) {
              setCameFromTrend(false);
              router.push("/intelligence");
            }
          }
        }}
      >
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            {cameFromTrend && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="self-start -ml-2 mb-1 h-7 px-2 text-xs text-muted-foreground"
                onClick={() => {
                  setDialogOpen(false);
                }}
              >
                <ArrowLeft className="mr-1 h-3.5 w-3.5" />
                Back to Intelligence
              </Button>
            )}
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

            {/* Type (post vs reel) */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Type</label>
              <div className="flex gap-2">
                {(["post", "reel"] as const).map((t) => (
                  <Button
                    key={t}
                    type="button"
                    size="sm"
                    variant={formItemType === t ? "default" : "outline"}
                    onClick={() => setFormItemType(t)}
                  >
                    {t === "post" ? "Post" : "Reel"}
                  </Button>
                ))}
              </div>
              {formItemType === "reel" && (
                <p className="text-xs text-muted-foreground">
                  Reels generate a short vertical video (9:16) instead of a static image.
                </p>
              )}
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
