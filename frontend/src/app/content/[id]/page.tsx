"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { AlertTriangle, ArrowLeft, Eye, Edit3, Clock, CheckCircle, XCircle, Loader2, Trash2, CalendarClock, MessageSquare, Upload, Film } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ContentEditor } from "@/components/content/ContentEditor";
import { ChannelPreview } from "@/components/content/ChannelPreview";
import { LogoEditor, type LogoPlacement } from "@/components/content/LogoEditor";

import { ApprovalHistory } from "@/components/approval/ApprovalHistory";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { api, fileUrl, generateVideo, isAuthError } from "@/lib/api";
import { useOpenedContent } from "@/lib/opened-content";
import { toApiDatetime } from "@/lib/utils";
import type { Content, Approval, CalendarItem, Brand } from "@/types";

function safeHashtags(raw: unknown): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(String);
  if (typeof raw === "string") {
    try { const p = JSON.parse(raw); if (Array.isArray(p)) return p.map(String); } catch { /* ignore */ }
    return raw.split(",").map(s => s.trim()).filter(Boolean);
  }
  return [];
}

export default function ContentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const contentId = params.id as string;

  const [content, setContent] = useState<Content | null>(null);
  const [calendarItem, setCalendarItem] = useState<CalendarItem | null>(null);
  const [brand, setBrand] = useState<Brand | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [approvalComments, setApprovalComments] = useState("");
  const [submittingApproval, setSubmittingApproval] = useState(false);
  const [imagePrompt, setImagePrompt] = useState("");
  const [regeneratingImage, setRegeneratingImage] = useState(false);
  const [regeneratingCaption, setRegeneratingCaption] = useState(false);
  const [generatingVideo, setGeneratingVideo] = useState(false);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [logoEditMode, setLogoEditMode] = useState(false);
  const [savingLogo, setSavingLogo] = useState(false);
  const imageUploadInputRef = useRef<HTMLInputElement>(null);
  const [imageCacheBust, setImageCacheBust] = useState("");
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduleTime, setScheduleTime] = useState("09:00");
  const [scheduling, setScheduling] = useState(false);
  const [passingToReview, setPassingToReview] = useState(false);
  const [retryingPublish, setRetryingPublish] = useState(false);
  // Degraded-outcome flags from the latest video render job (audio_finish,
  // label_guard live only on video_jobs, not on content.generation_metadata).
  const [videoJobFlags, setVideoJobFlags] = useState<Record<string, unknown> | null>(null);
  const { markOpened } = useOpenedContent();

  // The URL param is the calendar item id — flag it as seen so the "New"
  // badge stops showing for it in the Kanban / stage views.
  useEffect(() => {
    if (contentId) markOpened(contentId);
  }, [contentId, markOpened]);

  useEffect(() => {
    async function fetchData() {
      try {
        let contentData: Content | null = null;
        try {
          contentData = await api.get<Content>(`/api/v1/content/by-calendar-item/${contentId}`);
        } catch {
          try {
            contentData = await api.get<Content>(`/api/v1/content/${contentId}`);
          } catch { /* neither worked */ }
        }
        if (!contentData) {
          // No content row — generation may have died before creating one.
          // The URL param is the calendar item id, so fetch it directly:
          // without it the "not yet generated" screen would hide a FAILED
          // item's error and actions behind a forever-pending message.
          try {
            const calItem = await api.get<CalendarItem>(`/api/v1/calendar/${contentId}`);
            setCalendarItem(calItem);
          } catch { /* not a calendar item id either */ }
        }
        if (contentData) {
          setContent(contentData);
          // Fetch the calendar item for channel info
          if (contentData.calendar_item_id) {
            try {
              const calItem = await api.get<CalendarItem>(`/api/v1/calendar/${contentData.calendar_item_id}`);
              setCalendarItem(calItem);
              // Pre-fill schedule date/time from calendar item
              if (calItem.scheduled_at) {
                const d = new Date(calItem.scheduled_at);
                setScheduleDate(d.toLocaleDateString("en-CA")); // YYYY-MM-DD format
                setScheduleTime(d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })); // HH:MM format
              }
            } catch { /* optional */ }
          }
          // Fetch brand for name/handle
          if (contentData.brand_id) {
            try {
              const brandData = await api.get<Brand>(`/api/v1/brands/${contentData.brand_id}`);
              setBrand(brandData);
            } catch { /* optional */ }
          }
          // Fetch approvals
          try {
            const approvalData = await api.get<{ items: Approval[] } | Approval[]>(`/api/v1/approvals`, { content_id: contentData.id });
            const approvalList = Array.isArray(approvalData) ? approvalData : (approvalData as { items: Approval[] }).items || [];
            setApprovals(approvalList);
          } catch { /* optional */ }
        }
      } catch (err) {
        // Session expiry mid-load: the client is already redirecting to
        // sign-in — an error toast here would be a lie flashing over it.
        if (!isAuthError(err)) toast.error("Failed to load content");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [contentId]);

  const handleSave = useCallback(async (data: Partial<Content>) => {
    try {
      const actualId = content?.id || contentId;
      const updated = await api.put<Content>(`/api/v1/content/${actualId}`, data);
      setContent(updated);
      toast.success("Content saved");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to save content";
      toast.error(detail);
    }
  }, [content, contentId]);

  const handleRegenerateImage = useCallback(async (format: "lifestyle" | "ad" = "lifestyle") => {
    if (!content) return;
    setRegeneratingImage(true);
    try {
      // Snapshot the image identity BEFORE queueing: a new branded image can
      // land at the SAME object path (branded.png), so updated_at (bumped by
      // a DB trigger on every content write) is the tiebreaker for "did the
      // worker actually produce something".
      const imageOf = (c: Content) => (
        c.generation_metadata?.branded_image ||
        c.generation_metadata?.raw_image ||
        c.generation_metadata?.generated_image_url ||
        ""
      ) as string;
      const beforePath = imageOf(content);
      const beforeUpdatedAt = content.updated_at;

      await api.post(`/api/v1/content/${content.id}/regenerate-image`, {
        prompt: imagePrompt || undefined,
        format,
      });
      toast.success(
        `${format === "ad" ? "Ad" : "Lifestyle"} image regeneration started — this may take a minute...`
      );

      // Poll for completion: check calendar item status until it leaves "working".
      // gpt-image models are slow (~2 min each) and regenerations are processed
      // sequentially, so poll up to ~5 minutes before giving up.
      const calItemId = content.calendar_item_id;
      if (calItemId) {
        const maxAttempts = 60; // ~5 minutes (60 × 5s)
        for (let i = 0; i < maxAttempts; i++) {
          await new Promise(r => setTimeout(r, 5000));
          try {
            const calItem = await api.get<CalendarItem>(`/api/v1/calendar/${calItemId}`);
            if (calItem.status !== "working") {
              // Reload content to get the new image
              const updated = await api.get<Content>(`/api/v1/content/${content.id}`);
              setContent(updated);
              setCalendarItem(calItem);
              setImageCacheBust(`_cb=${Date.now()}`);
              // Leaving 'working' only means the worker FINISHED, not that it
              // succeeded — on failure it restores the prior status with the
              // old image intact. Only claim success when the image actually
              // changed; otherwise surface the worker's recorded error.
              const changed =
                imageOf(updated) !== beforePath || updated.updated_at !== beforeUpdatedAt;
              const workerError =
                (typeof updated.generation_metadata?.regen_error === "string"
                  ? updated.generation_metadata.regen_error
                  : undefined) ||
                (typeof calItem.generation_metadata?.regen_error === "string"
                  ? calItem.generation_metadata.regen_error
                  : undefined);
              if (changed) {
                toast.success("Image regenerated successfully");
              } else if (workerError) {
                toast.error(`Image regeneration failed: ${workerError}`);
              } else {
                toast.error("Image regeneration finished without producing a new image — please try again.");
              }
              break;
            }
          } catch { /* keep polling */ }
        }
      }
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to regenerate image";
      toast.error(detail);
    } finally {
      setRegeneratingImage(false);
    }
  }, [content, imagePrompt]);

  const handleRegenerateCaption = useCallback(async () => {
    if (!content) return;
    setRegeneratingCaption(true);
    try {
      const updated = await api.post<Content>(
        `/api/v1/content/${content.id}/regenerate-caption`,
        {}
      );
      setContent(updated);
      toast.success("Caption regenerated");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to regenerate caption";
      toast.error(detail);
    } finally {
      setRegeneratingCaption(false);
    }
  }, [content]);

  const handleGenerateVideo = useCallback(async () => {
    if (!content) return;
    setGeneratingVideo(true);
    try {
      await generateVideo(content.id);
      toast.success("Video generation started — this may take a few minutes...");
      // The backend flips the calendar item to "rendering" in the same request;
      // mirror it locally so the progress banner + poll loop (effect below)
      // take over immediately.
      setCalendarItem((prev) => (prev ? { ...prev, status: "rendering" } : prev));
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to start video generation";
      toast.error(detail);
    } finally {
      setGeneratingVideo(false);
    }
  }, [content]);

  // While a reel render is in flight, poll the calendar item until it settles,
  // then reload the content so the finished video appears — same pattern as
  // the regenerate-image wait-loop, but hung on the status so a page reload
  // mid-render picks the poll back up. The backend flips the item through
  // queued → working → rendering before landing in in_review/failed, so all
  // three count as in-flight — completing on the first non-"rendering" tick
  // would fire at t=5s while the item is still merely queued.
  useEffect(() => {
    const inFlight = (s?: string) => ["queued", "working", "rendering"].includes(s || "");
    const reel = calendarItem?.item_type === "reel" || content?.content_type === "reel";
    if (!calendarItem || !reel || !inFlight(calendarItem.status)) return;
    const calItemId = calendarItem.id;
    let cancelled = false;
    (async () => {
      const maxAttempts = 120; // ~10 minutes (120 × 5s) — video renders are slow
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise(r => setTimeout(r, 5000));
        if (cancelled) return;
        try {
          const calItem = await api.get<CalendarItem>(`/api/v1/calendar/${calItemId}`);
          if (cancelled) return;
          if (!inFlight(calItem.status)) {
            setCalendarItem(calItem);
            // store_video creates a NEW content row (the old one is flipped
            // to is_current=false) — refetch by calendar item, not by the
            // stale content id, so video_url actually lands in state.
            try {
              const updated = await api.get<Content>(`/api/v1/content/by-calendar-item/${calItemId}`);
              if (cancelled) return;
              setContent(updated);
              setImageCacheBust(`_cb=${Date.now()}`);
            } catch { /* keep the old row if the refetch fails */ }
            if (calItem.status === "failed") toast.error("Video render failed");
            else toast.success("Video rendered");
            return;
          }
        } catch { /* keep polling */ }
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calendarItem?.status, calendarItem?.id, calendarItem?.item_type, content?.content_type]);

  // Pull the latest render job's quality flags so review can SEE the
  // degraded outcomes the pipeline recorded (record-don't-block contract:
  // audio_finish / label_guard are measured but live only on video_jobs).
  useEffect(() => {
    // Legacy items carry item_type "video" instead of "reel" — their render
    // jobs record the same quality flags, so fetch for both.
    const hasVideoJobs =
      calendarItem?.item_type === "reel" ||
      calendarItem?.item_type === "video" ||
      content?.content_type === "reel" ||
      content?.content_type === "video";
    if (!content?.id || !hasVideoJobs) return;
    let cancelled = false;
    (async () => {
      try {
        const jobs = await api.get<{ status: string; quality_flags?: Record<string, unknown> }[]>(
          `/api/v1/content/${content.id}/video-jobs`
        );
        if (cancelled || !Array.isArray(jobs)) return;
        const latest = jobs.find((j) => j.status === "succeeded") || jobs[0];
        setVideoJobFlags(latest?.quality_flags || null);
      } catch { /* advisory only — never block the page on this */ }
    })();
    return () => { cancelled = true; };
  }, [content?.id, calendarItem?.item_type, content?.content_type]);

  const handleUploadImage = useCallback(async (file: File) => {
    if (!content) return;
    const allowed = ["image/png", "image/jpeg", "image/webp"];
    if (!allowed.includes(file.type)) {
      toast.error("Only PNG, JPEG, or WebP images are allowed");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error("File size must be under 5MB");
      return;
    }
    setUploadingImage(true);
    try {
      const updated = await api.uploadFile<Content>(`/api/v1/content/${content.id}/upload-image`, file);
      setContent(updated);
      setImageCacheBust(`_cb=${Date.now()}`);
      toast.success("Image uploaded");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to upload image";
      toast.error(detail);
    } finally {
      setUploadingImage(false);
      if (imageUploadInputRef.current) imageUploadInputRef.current.value = "";
    }
  }, [content]);

  const handleSaveLogo = useCallback(async (placement: LogoPlacement) => {
    if (!content) return;
    setSavingLogo(true);
    try {
      await api.post(`/api/v1/content/${content.id}/rebrand-logo`, placement);
      toast.success("Logo re-render started…");
      // Poll until the calendar item leaves "working", then reload the image.
      const calItemId = content.calendar_item_id;
      if (calItemId) {
        const maxAttempts = 40; // ~80s
        for (let i = 0; i < maxAttempts; i++) {
          await new Promise(r => setTimeout(r, 2000));
          try {
            const calItem = await api.get<CalendarItem>(`/api/v1/calendar/${calItemId}`);
            if (calItem.status !== "working") {
              const updated = await api.get<Content>(`/api/v1/content/${content.id}`);
              setContent(updated);
              setCalendarItem(calItem);
              setImageCacheBust(`_cb=${Date.now()}`);
              toast.success("Logo updated");
              break;
            }
          } catch { /* keep polling */ }
        }
      }
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to re-render logo";
      toast.error(detail);
    } finally {
      setSavingLogo(false);
      setLogoEditMode(false);
    }
  }, [content]);

  const handleApproval = useCallback(async (action: "approved" | "rejected") => {
    const pendingApproval = approvals.find(a => a.status === "pending");
    if (!pendingApproval) {
      toast.error("No pending approval found");
      return;
    }
    setSubmittingApproval(true);
    try {
      await api.put(`/api/v1/approvals/${pendingApproval.id}`, {
        status: action,
        feedback: approvalComments || undefined,
      });
      toast.success(`Content ${action}`);
      // Refresh approvals
      const approvalData = await api.get<{ items: Approval[] } | Approval[]>(`/api/v1/approvals`, { content_id: content?.id });
      const approvalList = Array.isArray(approvalData) ? approvalData : (approvalData as { items: Approval[] }).items || [];
      setApprovals(approvalList);
      setApprovalComments("");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || `Failed to ${action} content`;
      toast.error(detail);
    } finally {
      setSubmittingApproval(false);
    }
  }, [approvals, approvalComments, content]);

  const handleSchedule = useCallback(async () => {
    if (!calendarItem?.id || !scheduleDate) {
      toast.error("Please select a date");
      return;
    }
    setScheduling(true);
    try {
      const scheduledAt = toApiDatetime(`${scheduleDate}T${scheduleTime}:00`);
      if (!scheduledAt) {
        toast.error("Invalid date or time");
        return;
      }
      await api.patch(`/api/v1/calendar/${calendarItem.id}`, {
        status: "scheduled",
        scheduled_at: scheduledAt,
      });
      toast.success("Content scheduled for publishing");
      // Refresh calendar item
      const updated = await api.get<CalendarItem>(`/api/v1/calendar/${calendarItem.id}`);
      setCalendarItem(updated);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to schedule content";
      toast.error(detail);
    } finally {
      setScheduling(false);
    }
  }, [calendarItem, scheduleDate, scheduleTime]);

  const handleUpdateSchedule = useCallback(async () => {
    if (!calendarItem?.id || !scheduleDate) {
      toast.error("Please select a date");
      return;
    }
    setScheduling(true);
    try {
      const scheduledAt = toApiDatetime(`${scheduleDate}T${scheduleTime}:00`);
      if (!scheduledAt) {
        toast.error("Invalid date or time");
        return;
      }
      await api.patch(`/api/v1/calendar/${calendarItem.id}`, {
        scheduled_at: scheduledAt,
      });
      toast.success("Schedule updated");
      const updated = await api.get<CalendarItem>(`/api/v1/calendar/${calendarItem.id}`);
      setCalendarItem(updated);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update schedule";
      toast.error(detail);
    } finally {
      setScheduling(false);
    }
  }, [calendarItem, scheduleDate, scheduleTime]);

  const handlePassToReview = useCallback(async () => {
    if (!calendarItem?.id) return;
    setPassingToReview(true);
    try {
      await api.patch(`/api/v1/calendar/${calendarItem.id}`, { status: "in_review" });
      toast.success("Moved to In Review");
      const updated = await api.get<CalendarItem>(`/api/v1/calendar/${calendarItem.id}`);
      setCalendarItem(updated);
      // The backend recreated a pending approval — refresh so Approve/Reject
      // reappear without a manual page reload.
      if (content?.id) {
        const approvalData = await api.get<{ items: Approval[] } | Approval[]>(
          `/api/v1/approvals`,
          { content_id: content.id }
        );
        const approvalList = Array.isArray(approvalData)
          ? approvalData
          : (approvalData as { items: Approval[] }).items || [];
        setApprovals(approvalList);
      }
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to move to In Review";
      toast.error(detail);
    } finally {
      setPassingToReview(false);
    }
  }, [calendarItem, content]);

  const handleDiscard = useCallback(async () => {
    if (!calendarItem?.id) {
      toast.error("No calendar item to discard");
      return;
    }
    if (!window.confirm("Are you sure you want to permanently discard this content? This cannot be undone.")) {
      return;
    }
    try {
      await api.delete(`/api/v1/calendar/${calendarItem.id}`);
      toast.success("Content discarded");
      router.push("/content");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to discard content";
      toast.error(detail);
    }
  }, [calendarItem, router]);

  // failed → scheduled is the "retry publish" path the publish checker acts
  // on. A scheduled_at that is already past must move forward with it: the
  // checker EXPIRES anything more than a day overdue, so retrying a
  // Monday-scheduled post on Wednesday with the old timestamp would silently
  // re-fail. A couple of minutes out keeps "publishes right away" honest
  // while landing inside the checker's next sweep.
  const handleRetryPublish = useCallback(async () => {
    if (!calendarItem?.id) return;
    setRetryingPublish(true);
    try {
      const patch: { status: string; scheduled_at?: string } = { status: "scheduled" };
      if (calendarItem.scheduled_at && new Date(calendarItem.scheduled_at) < new Date()) {
        patch.scheduled_at = new Date(Date.now() + 2 * 60 * 1000).toISOString();
      }
      await api.patch(`/api/v1/calendar/${calendarItem.id}`, patch);
      toast.success("Publish retry queued — the post is scheduled again");
      const updated = await api.get<CalendarItem>(`/api/v1/calendar/${calendarItem.id}`);
      setCalendarItem(updated);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to retry publishing";
      toast.error(detail);
    } finally {
      setRetryingPublish(false);
    }
  }, [calendarItem]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-[600px] w-full" />
      </div>
    );
  }

  if (!content) {
    // A failed item with no content row: generation died before producing
    // anything. "Still being processed" would be a lie here — show the
    // recorded error and the one action that works without content (the
    // regenerate endpoints are content-scoped, so they can't be offered).
    if (calendarItem?.status === "failed") {
      const calMeta = (calendarItem.generation_metadata || {}) as Record<string, unknown>;
      const generationError = typeof calMeta.last_error === "string" ? calMeta.last_error : undefined;
      return (
        <div className="text-center py-12 max-w-lg mx-auto">
          <XCircle className="h-8 w-8 text-red-500 mx-auto" />
          <p className="text-lg font-medium mt-2">Generation failed</p>
          <p className="text-sm text-muted-foreground mt-1">
            {generationError
              ? generationError
              : "Content generation failed before anything was produced, and no error details were recorded."}
          </p>
          <div className="flex justify-center gap-2 mt-4">
            <Button variant="outline" onClick={() => router.push("/content")}>
              Back to Content Studio
            </Button>
            <Button variant="destructive" onClick={handleDiscard}>
              <Trash2 className="mr-1.5 h-4 w-4" />
              Discard
            </Button>
          </div>
        </div>
      );
    }
    // Check if this is a calendar item that hasn't had content generated yet
    return (
      <div className="text-center py-12">
        <p className="text-lg text-muted-foreground">Content not yet generated</p>
        <p className="text-sm text-muted-foreground mt-1">
          This item is still being processed. Content will appear once generation completes.
        </p>
        <Button variant="outline" className="mt-4" onClick={() => router.push("/content")}>
          Back to Content Studio
        </Button>
      </div>
    );
  }

  const channel = calendarItem?.channel || content.platform || "instagram";
  const brandName = brand?.name || "Brand";
  // Derive handle: channels.instagram.handle → brand slug → name-based fallback
  const brandHandle = (() => {
    const channels = (brand?.brand_guidelines as Record<string, unknown>)?.channels as Record<string, Record<string, string>> | undefined;
    const igHandle = channels?.instagram?.handle;
    if (igHandle) return igHandle.replace(/^@/, "");
    if (brand?.slug) return brand.slug;
    return brandName.toLowerCase().replace(/\s+/g, "");
  })();
  // Resolve avatar: prefer watermark/icon logo (compact), fall back to logo_url
  const brandAvatarUrl = (() => {
    const logos = (brand?.brand_guidelines as Record<string, unknown>)?.logos as Record<string, Record<string, string>> | undefined;
    for (const variant of ["watermark", "icon", "secondary", "primary"]) {
      const url = logos?.[variant]?.url;
      if (url) return fileUrl(url);
    }
    if (brand?.logo_url) return fileUrl(brand.logo_url);
    return undefined;
  })();
  const caption = content.caption || content.body_text || "";
  const hashtags = safeHashtags(content.hashtags);
  const hasPendingApproval = approvals.some(a => a.status === "pending");
  // Scheduled & published are read-only: no Edit/History tabs, no image or
  // schedule editing. Scheduled gets a single "Cancel → In Review" action.
  const isViewOnly = ["scheduled", "published"].includes(calendarItem?.status || "");
  // Resolve image URL from generation_metadata — prefer branded (has logo+text) over raw
  const imagePath = (
    content.generation_metadata?.branded_image ||
    content.generation_metadata?.raw_image ||
    content.generation_metadata?.generated_image_url ||
    ""
  ) as string;
  // Cache key: prefer the post-save timestamp (imageCacheBust); otherwise key
  // on content.updated_at (bumped by a DB trigger on every edit) so a NEW
  // branded image at the SAME `branded.png` path is refetched after a page
  // reload (F5) instead of serving the 1h browser-cached old version.
  const imageVersion = imageCacheBust || (content.updated_at ? `v=${encodeURIComponent(content.updated_at)}` : "");
  const contentImageUrl = imagePath
    ? fileUrl(imagePath) + (imageVersion ? `?${imageVersion}` : "")
    : undefined;
  // Thumbnail for faster preview loading (600px wide, quality 75)
  const contentThumbUrl = contentImageUrl
    ? `${contentImageUrl}${contentImageUrl.includes("?") ? "&" : "?"}w=600&q=75`
    : undefined;
  // ── Video (reels) ──────────────────────────────────────────────
  // Media resolution branches on item_type/content_type + video_url: reels
  // render the video player (with the keyframe image as poster) instead of
  // the image once the render lands.
  const isReel = calendarItem?.item_type === "reel" || content.content_type === "reel";
  // A reel render is in flight from the moment it's queued (queued → working
  // → rendering) — mirror the poll effect above so the banner tracks it all.
  const isRendering = ["queued", "working", "rendering"].includes(calendarItem?.status || "");
  const contentVideoUrl = content.video_url
    ? fileUrl(content.video_url) + (imageVersion ? `?${imageVersion}` : "")
    : undefined;

  // ── Logo / overlay visual editor inputs ────────────────────────
  const gm = (content.generation_metadata || {}) as Record<string, unknown>;
  // Editor backdrop is the CLEAN image (no logo/text); fall back to raw.
  const composedPath = (gm.composed_image || gm.raw_image) as string | undefined;
  const cleanImageUrl = composedPath
    ? fileUrl(composedPath) + (imageCacheBust ? `?${imageCacheBust}` : "")
    : undefined;
  // All brand logo variants (label → absolute url) for the reverse button.
  const availableLogos = (() => {
    const logos = (brand?.brand_guidelines as Record<string, unknown> | undefined)?.logos as Record<string, Record<string, string>> | undefined;
    const map: Record<string, string> = {};
    if (logos) {
      for (const [label, info] of Object.entries(logos)) {
        if (info?.url) map[label] = fileUrl(info.url);
      }
    }
    return map;
  })();
  // Prefer the exact logo variant that was composited; else the avatar logo.
  const logoEditorUrl = (() => {
    const variant = gm.logo_variant_used as string | undefined;
    if (variant && availableLogos[variant]) return availableLogos[variant];
    return brandAvatarUrl;
  })();
  const editorTextLine1 = (gm.hook as string) || content.headline || content.title || caption.split("\n")[0] || "";
  const editorTextLine2 = `${brandName}${brand?.website_url ? ` — ${brand.website_url}` : ""}`;
  const initialPlacement = {
    logo_xy: (gm.logo_xy as [number, number] | undefined) || ([0.85, 0.85] as [number, number]),
    logo_scale: (gm.logo_scale as number | undefined) || 0.2,
    text_xy: (gm.text_xy as [number, number] | null | undefined) || null,
    text_scale: (gm.text_scale as number | undefined) || 1,
    text_style: (gm.text_style as string | undefined) || "glass",
    font_family: (gm.font_family as string | undefined) || undefined,
    headline_colors: (gm.headline_colors as Record<string, string> | undefined) || undefined,
    text_width: (gm.text_width as number | undefined) ?? undefined,
    product_logo_xy: (gm.product_logo_xy as [number, number] | undefined) || undefined,
    product_logo_scale: (gm.product_logo_scale as number | undefined) ?? undefined,
    product_logo_enabled: (gm.product_logo_enabled as boolean | undefined) ?? undefined,
    product_logo_variant: (gm.product_logo_variant as string | undefined) || undefined,
    textAnchor: (gm.text_anchor_used as string | undefined) || null,
  };
  // The product (manufacturer) logo, served from MinIO if the product has one.
  const productLogoUrl = gm.product_logo_image ? fileUrl(gm.product_logo_image as string) : undefined;
  // Light/dark variant URLs for the editor's manual swap button. Prefer the
  // variants saved on the post; otherwise resolve them from the brand's
  // vendor_logos by matching the current logo object (so posts generated before
  // the variants feature still get the swap button).
  const productLogoUrls = (() => {
    const metaVars = gm.product_logo_variants as Record<string, string> | undefined;
    if (metaVars && (metaVars.light || metaVars.dark)) {
      return {
        light: metaVars.light ? fileUrl(metaVars.light) : undefined,
        dark: metaVars.dark ? fileUrl(metaVars.dark) : undefined,
      };
    }
    const gl = brand?.brand_guidelines as Record<string, unknown> | undefined;
    // Merge vendor + category logos so the swap button also resolves variants
    // for products whose logo came from the category fallback.
    const vl = {
      ...((gl?.vendor_logos as Record<string, Record<string, unknown>>) || {}),
      ...((gl?.category_logos as Record<string, Record<string, unknown>>) || {}),
    };
    const cur = gm.product_logo_image as string | undefined;
    if (!cur || Object.keys(vl).length === 0) return undefined;
    const curSlug = cur.split("/").pop()?.replace(/-(light|dark)\.[a-z0-9]+$/i, "").replace(/\.[a-z0-9]+$/i, "");
    for (const entry of Object.values(vl)) {
      const lightE = (entry?.light as Record<string, string> | undefined) || undefined;
      const darkE = (entry?.dark as Record<string, string> | undefined) || undefined;
      const lightObj = lightE?.object_name ?? (entry?.object_name as string | undefined); // legacy flat = light
      const darkObj = darkE?.object_name;
      const lightSlug = lightE?.slug ?? (entry?.slug as string | undefined);
      const darkSlug = darkE?.slug;
      if (cur === lightObj || cur === darkObj || (curSlug && (curSlug === lightSlug || curSlug === darkSlug))) {
        return {
          light: lightObj ? fileUrl(lightObj) : undefined,
          dark: darkObj ? fileUrl(darkObj) : undefined,
        };
      }
    }
    return undefined;
  })();
  const canEditLogo = !!calendarItem && ["in_review", "reworking"].includes(calendarItem.status) && !!cleanImageUrl;

  // Latest reviewer remark (rejection feedback) for this content, if any.
  const latestRemark = (() => {
    const withFb = approvals.filter((a) => (a.feedback || a.comments || "").trim());
    if (!withFb.length) return null;
    const top = [...withFb].sort(
      (a, b) =>
        new Date(b.decided_at || b.created_at).getTime() -
        new Date(a.decided_at || a.created_at).getTime()
    )[0];
    return {
      text: (top.feedback || top.comments) as string,
      by: top.reviewer_name,
      at: top.decided_at || top.created_at,
    };
  })();

  // ── Degraded-outcome quality flags (audit §6 "last mile") ──────────
  // The pipeline measures and persists every degraded outcome but nothing
  // downstream read them, so review looked "normal". Collect the ones that
  // indicate real degradation from content.generation_metadata + the latest
  // video job and surface them as a warning banner.
  const qualityIssues = (() => {
    const issues: { key: string; detail: string }[] = [];
    const overlayBurn = (gm.overlay_burn ?? videoJobFlags?.overlay_burn) as string | undefined;
    if (typeof overlayBurn === "string" && overlayBurn.startsWith("failed")) {
      issues.push({ key: "overlay_burn", detail: overlayBurn });
    }
    const multishotFallback = gm.multishot_fallback ?? videoJobFlags?.multishot_fallback;
    if (multishotFallback) {
      issues.push({ key: "multishot_fallback", detail: String(multishotFallback) });
    }
    const audioFinish = videoJobFlags?.audio_finish;
    if (typeof audioFinish === "string" && (audioFinish.startsWith("failed") || audioFinish.startsWith("silent"))) {
      issues.push({ key: "audio_finish", detail: audioFinish });
    }
    const labelGuard = videoJobFlags?.label_guard as Record<string, unknown> | undefined;
    if (labelGuard && typeof labelGuard === "object" && labelGuard.flagged) {
      const flags = Array.isArray(labelGuard.flags) ? (labelGuard.flags as unknown[]).map(String).join(", ") : "flagged frames";
      issues.push({ key: "label_guard", detail: flags });
    }
    const brandingReview = gm.branding_review as Record<string, unknown> | undefined;
    if (brandingReview && typeof brandingReview === "object") {
      if (brandingReview.ok === false) {
        issues.push({ key: "branding_review", detail: String(brandingReview.reason ?? "review failed") });
      } else if (brandingReview.copy_contract_ok === false) {
        issues.push({ key: "branding_review", detail: "copy contract breach detected" });
      }
    }
    return issues;
  })();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => {
              // Return to wherever the user came from (a stage list, the grid,
              // calendar, approvals…), falling back to Content Studio.
              if (typeof window !== "undefined" && window.history.length > 1) {
                router.back();
              } else {
                router.push("/content");
              }
            }}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-3xl font-bold">{content.title || content.headline || "Content"}</h1>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="outline" className="capitalize">{channel}</Badge>
              {calendarItem?.scheduled_at && (
                <span className="text-xs text-muted-foreground">
                  Scheduled: {new Date(calendarItem.scheduled_at).toLocaleDateString()} at {new Date(calendarItem.scheduled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Pipeline quality warnings — visible on every tab so a reviewer
          can't approve without seeing what the render degraded. */}
      {qualityIssues.length > 0 && (
        <Card className="border-amber-500/50 bg-amber-500/10">
          <CardContent className="py-3">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
              <div className="space-y-1.5">
                <p className="text-sm font-medium">
                  Pipeline reported degraded outcomes: {qualityIssues.map((i) => i.key).join(", ")}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {qualityIssues.map((i) => (
                    <Badge
                      key={i.key}
                      variant="outline"
                      className="border-amber-500/60 text-amber-700 dark:text-amber-400 text-xs font-normal"
                    >
                      {i.key}: {i.detail}
                    </Badge>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  The render finished, but with recorded quality degradations — review the media carefully before approving.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="preview">
        <TabsList>
          <TabsTrigger value="preview" className="gap-1.5">
            <Eye className="h-3.5 w-3.5" /> Preview
          </TabsTrigger>
          {!isViewOnly && (
            <TabsTrigger value="edit" className="gap-1.5">
              <Edit3 className="h-3.5 w-3.5" /> Edit
            </TabsTrigger>
          )}
          {!isViewOnly && (
            <TabsTrigger value="history" className="gap-1.5">
              <Clock className="h-3.5 w-3.5" /> History
            </TabsTrigger>
          )}
        </TabsList>

        {/* Preview Tab */}
        <TabsContent value="preview" className="mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="flex justify-center">
              {logoEditMode && cleanImageUrl ? (
                <div className="w-full">
                  <LogoEditor
                    cleanImageUrl={cleanImageUrl}
                    logoUrl={logoEditorUrl}
                    productLogoUrl={productLogoUrl}
                    productLogoUrls={productLogoUrls}
                    logos={availableLogos}
                    initialVariant={(gm.logo_variant_used as string) || undefined}
                    textLine1={editorTextLine1}
                    textLine2={editorTextLine2}
                    initial={initialPlacement}
                    saving={savingLogo}
                    onSave={handleSaveLogo}
                    onCancel={() => setLogoEditMode(false)}
                  />
                </div>
              ) : (
                <div className="relative">
                  <ChannelPreview
                    channel={channel}
                    brandName={brandName}
                    brandHandle={brandHandle}
                    avatarUrl={brandAvatarUrl}
                    caption={caption}
                    hashtags={hashtags}
                    imageUrl={contentThumbUrl || contentImageUrl}
                    videoUrl={contentVideoUrl}
                    cta={content.cta || content.cta_text}
                    imageOverlay={canEditLogo ? (
                      <Button
                        type="button"
                        size="icon"
                        variant="secondary"
                        onClick={(e) => { e.stopPropagation(); setLogoEditMode(true); }}
                        className="h-8 w-8 rounded-full shadow-md"
                        title="Edit logo & text placement"
                        aria-label="Edit logo"
                      >
                        <Edit3 className="h-4 w-4" />
                      </Button>
                    ) : undefined}
                  />
                </div>
              )}
            </div>
            <div className="space-y-4">
              {/* Approval actions */}
              {hasPendingApproval && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Review & Approve</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Textarea
                      placeholder="Add feedback or comments (optional)..."
                      value={approvalComments}
                      onChange={(e) => setApprovalComments(e.target.value)}
                      rows={3}
                    />
                    <div className="flex gap-2">
                      <Button
                        className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white dark:bg-emerald-700 dark:hover:bg-emerald-600"
                        disabled={submittingApproval}
                        onClick={() => handleApproval("approved")}
                      >
                        <CheckCircle className="mr-1.5 h-4 w-4" />
                        Approve
                      </Button>
                      <Button
                        variant="destructive"
                        className="flex-1"
                        disabled={submittingApproval}
                        onClick={() => handleApproval("rejected")}
                      >
                        <XCircle className="mr-1.5 h-4 w-4" />
                        Reject
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Failed — explain what went wrong and offer the recovery actions */}
              {calendarItem && calendarItem.status === "failed" && (() => {
                const calMeta = (calendarItem.generation_metadata || {}) as Record<string, unknown>;
                // Two failure families write two different fields: the
                // content/video worker records last_error on the CALENDAR
                // ITEM's metadata; the publish pipeline records publish_error
                // on the CONTENT's metadata. Render whichever exists.
                const generationError = typeof calMeta.last_error === "string" ? calMeta.last_error : undefined;
                const publishError = typeof gm.publish_error === "string" ? gm.publish_error : undefined;
                // A recorded publish_error means the post already passed
                // review and died at the publishing step — retrying the
                // publish is the fix. A pure generation/render failure never
                // reached review, so re-scheduling it would push an
                // unapproved post straight to publishing; hide the button
                // then. With no error recorded we can't tell, so offer it.
                const showRetryPublish = !!publishError || !generationError;
                return (
                  <Card className="border-red-500/40 bg-red-500/5">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base flex items-center gap-1.5">
                        <XCircle className="h-4 w-4 text-red-500" />
                        Failed
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {publishError || generationError ? (
                        <div className="space-y-2">
                          {publishError && (
                            <div>
                              <p className="text-xs font-medium text-red-600 dark:text-red-400">Publishing error</p>
                              <p className="text-sm whitespace-pre-wrap break-words">{publishError}</p>
                            </div>
                          )}
                          {generationError && (
                            <div>
                              <p className="text-xs font-medium text-red-600 dark:text-red-400">Generation error</p>
                              <p className="text-sm whitespace-pre-wrap break-words">{generationError}</p>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          Something went wrong, but no error details were recorded. You can retry below.
                        </p>
                      )}
                      <div className="space-y-3">
                        {showRetryPublish && (
                          <div className="space-y-1">
                            <Button
                              size="sm"
                              variant="outline"
                              className="w-full"
                              disabled={retryingPublish}
                              onClick={handleRetryPublish}
                            >
                              {retryingPublish ? (
                                <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                              ) : (
                                <CalendarClock className="mr-1.5 h-3 w-3" />
                              )}
                              Retry publish
                            </Button>
                            <p className="text-xs text-muted-foreground">
                              Puts the post back in the publishing queue
                              {calendarItem.scheduled_at
                                ? ` — it will publish at its scheduled time (${new Date(calendarItem.scheduled_at).toLocaleDateString()} ${new Date(calendarItem.scheduled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}), immediately if that has passed.`
                                : "."}
                            </p>
                          </div>
                        )}
                        <div className="space-y-1">
                          <Button
                            size="sm"
                            variant="outline"
                            className="w-full"
                            disabled={regeneratingImage || uploadingImage}
                            onClick={() => handleRegenerateImage("lifestyle")}
                          >
                            {regeneratingImage ? (
                              <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                            ) : (
                              <Edit3 className="mr-1.5 h-3 w-3" />
                            )}
                            Regenerate image
                          </Button>
                          <p className="text-xs text-muted-foreground">
                            Creates a fresh image and sends the post back to review.
                          </p>
                        </div>
                        {isReel && (
                          <div className="space-y-1">
                            <Button
                              size="sm"
                              variant="outline"
                              className="w-full"
                              disabled={generatingVideo || isRendering}
                              onClick={handleGenerateVideo}
                            >
                              {generatingVideo || isRendering ? (
                                <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                              ) : (
                                <Film className="mr-1.5 h-3 w-3" />
                              )}
                              Regenerate video
                            </Button>
                            <p className="text-xs text-muted-foreground">
                              Renders the reel again from scratch — this can take a few minutes.
                            </p>
                          </div>
                        )}
                        <div className="space-y-1">
                          <Button
                            size="sm"
                            variant="destructive"
                            className="w-full"
                            onClick={handleDiscard}
                          >
                            <Trash2 className="mr-1.5 h-3 w-3" />
                            Discard
                          </Button>
                          <p className="text-xs text-muted-foreground">
                            Permanently deletes this post. This cannot be undone.
                          </p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })()}

              {/* Scheduled — read-only: only action is Cancel (back to In Review) */}
              {calendarItem && calendarItem.status === "scheduled" && (
                <Card className="border-blue-500/30 bg-blue-500/5">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center gap-1.5">
                      <CalendarClock className="h-4 w-4 text-blue-500" />
                      Scheduled
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {calendarItem.scheduled_at && (
                      <p className="text-sm text-muted-foreground">
                        Will publish {new Date(calendarItem.scheduled_at).toLocaleDateString()} at {new Date(calendarItem.scheduled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </p>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={passingToReview}
                      onClick={handlePassToReview}
                      className="w-full"
                    >
                      {passingToReview ? (
                        <><Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> Cancelling...</>
                      ) : (
                        <><XCircle className="mr-1.5 h-4 w-4" /> Cancel — move to In Review</>
                      )}
                    </Button>
                  </CardContent>
                </Card>
              )}

              {/* Schedule editor — in_review only (NOT reworking/scheduled) */}
              {calendarItem && calendarItem.status === "in_review" && (
                <Card className="border-blue-500/30 bg-blue-500/5">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center gap-1.5">
                      <CalendarClock className="h-4 w-4 text-blue-500" />
                      Scheduled Date & Time
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs text-muted-foreground mb-1 block">Date</label>
                        <input
                          type="date"
                          value={scheduleDate}
                          onChange={(e) => setScheduleDate(e.target.value)}
                          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground mb-1 block">Time</label>
                        <input
                          type="time"
                          value={scheduleTime}
                          onChange={(e) => setScheduleTime(e.target.value)}
                          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={scheduling || !scheduleDate}
                      onClick={handleUpdateSchedule}
                      className="w-full"
                    >
                      {scheduling ? <><Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> Saving...</> : "Update Schedule"}
                    </Button>
                  </CardContent>
                </Card>
              )}

              {/* Reviewer remarks (rejection feedback) — reworking only */}
              {calendarItem && calendarItem.status === "reworking" && (
                <Card className={latestRemark ? "border-orange-500/40 bg-orange-500/5" : ""}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center gap-1.5">
                      <MessageSquare className="h-4 w-4 text-orange-500" />
                      Remarks
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {latestRemark ? (
                      <div className="space-y-1">
                        <p className="text-sm whitespace-pre-wrap">{latestRemark.text}</p>
                        <p className="text-xs text-muted-foreground">
                          — {latestRemark.by || "Reviewer"}
                          {latestRemark.at ? ` · ${new Date(latestRemark.at).toLocaleDateString()}` : ""}
                        </p>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">No remarks</p>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Pass to In Review + Discard — visible for in_review / reworking */}
              {calendarItem && ["in_review", "reworking"].includes(calendarItem.status) && (
                <div className="flex gap-2">
                  {calendarItem.status === "reworking" && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="flex-1"
                      disabled={passingToReview}
                      onClick={handlePassToReview}
                    >
                      {passingToReview ? (
                        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                      ) : (
                        <CheckCircle className="mr-1.5 h-4 w-4" />
                      )}
                      Pass to In Review
                    </Button>
                  )}
                  <Button
                    variant="destructive"
                    size="sm"
                    className="flex-1"
                    onClick={handleDiscard}
                  >
                    <Trash2 className="mr-1.5 h-4 w-4" />
                    Discard Content
                  </Button>
                </div>
              )}

              {/* Video generation — reels only */}
              {isReel && (() => {
                // Mirror the backend's _VIDEO_TRIGGER_ALLOWED_STATUSES
                // (content.py): a render may be (re)triggered only from
                // planned/queued/in_review/failed — notably INCLUDING failed
                // (retry) and excluding approved/scheduled/published. While a
                // render is in flight, keep the disabled spinner button
                // instead of the locked note.
                const videoLocked =
                  !!calendarItem &&
                  !isRendering &&
                  !["planned", "queued", "in_review", "failed"].includes(calendarItem.status);
                return (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Video</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {isRendering ? (
                        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          Rendering video — this may take a few minutes...
                        </p>
                      ) : content.video_url ? (
                        <p className="text-xs text-green-600">Video rendered</p>
                      ) : (
                        <p className="text-xs text-muted-foreground">No video rendered yet</p>
                      )}
                      {videoLocked ? (
                        <p className="text-xs text-muted-foreground">
                          Video editing is disabled for {calendarItem?.status} content.
                        </p>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={generatingVideo || isRendering}
                          onClick={handleGenerateVideo}
                          className="w-full"
                        >
                          {generatingVideo || isRendering ? (
                            <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                          ) : (
                            <Film className="mr-1.5 h-3 w-3" />
                          )}
                          {content.video_url ? "Regenerate Video" : "Generate Video"}
                        </Button>
                      )}
                    </CardContent>
                  </Card>
                );
              })()}

              {/* Image regeneration */}
              {(() => {
                // Mirrors the backend's _IMAGE_REGEN_ALLOWED_STATUSES
                // (content.py): regen is allowed from in_review/reworking AND
                // failed — it's the healing action the failed card above
                // offers (the worker finishes by flipping the item back to
                // in_review). Published/scheduled stay locked so an approved
                // post can't be silently un-approved.
                const imageLocked = !!calendarItem && ["published", "scheduled"].includes(calendarItem.status);
                return (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Image</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {content.generation_metadata?.user_uploaded_image ? (
                        <p className="text-xs text-green-600">Custom image uploaded</p>
                      ) : content.generation_metadata?.raw_image || content.generation_metadata?.generated_image_url ? (
                        <p className="text-xs text-green-600">Image generated</p>
                      ) : (
                        <p className="text-xs text-muted-foreground">No image generated yet</p>
                      )}
                      {imageLocked ? (
                        <p className="text-xs text-muted-foreground">
                          Image editing is disabled for {calendarItem?.status} content.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          <Textarea
                            placeholder="Custom image prompt (optional — leave blank to auto-generate from content)..."
                            value={imagePrompt}
                            onChange={(e) => setImagePrompt(e.target.value)}
                            rows={2}
                            className="text-xs"
                          />
                          <div className="grid grid-cols-2 gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={regeneratingImage || uploadingImage}
                              onClick={() => handleRegenerateImage("ad")}
                            >
                              {regeneratingImage ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : null}
                              Regenerate Image (Pub)
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={regeneratingImage || uploadingImage}
                              onClick={() => handleRegenerateImage("lifestyle")}
                            >
                              {regeneratingImage ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : null}
                              Regenerate Image (Lifestyle)
                            </Button>
                          </div>
                          <input
                            ref={imageUploadInputRef}
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            className="hidden"
                            onChange={(e) => {
                              const f = e.target.files?.[0];
                              if (f) handleUploadImage(f);
                            }}
                          />
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={regeneratingImage || uploadingImage}
                            onClick={() => imageUploadInputRef.current?.click()}
                            className="w-full"
                          >
                            {uploadingImage ? (
                              <><Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> Uploading...</>
                            ) : (
                              <><Upload className="mr-1.5 h-3 w-3" /> Upload Custom Image</>
                            )}
                          </Button>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })()}

              {/* Content details */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Content Details</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  {(content.cta || content.cta_text) ? (
                    <div>
                      <p className="text-xs text-muted-foreground">Call to Action</p>
                      <p>{String(content.cta || content.cta_text || "")}</p>
                    </div>
                  ) : null}
                  {hashtags.length > 0 && (
                    <div>
                      <p className="text-xs text-muted-foreground">Hashtags</p>
                      <p className="text-blue-500 text-xs">{hashtags.map(h => `#${h}`).join(" ")}</p>
                    </div>
                  )}
                  {(content.ai_model || content.ai_generated) ? (
                    <div>
                      <p className="text-xs text-muted-foreground">Generation</p>
                      <p className="text-xs">AI Generated{content.ai_model ? ` by ${String(content.ai_model)}` : ""}</p>
                    </div>
                  ) : null}
                </CardContent>
              </Card>

            </div>
          </div>
        </TabsContent>

        {/* Edit Tab */}
        {!isViewOnly && (
          <TabsContent value="edit" className="mt-6">
            <ContentEditor
              content={content}
              onSave={handleSave}
              onRegenerateCaption={handleRegenerateCaption}
              regeneratingCaption={regeneratingCaption}
            />
          </TabsContent>
        )}

        {/* History Tab */}
        {!isViewOnly && (
          <TabsContent value="history" className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Approval History</CardTitle>
              </CardHeader>
              <CardContent>
                <ApprovalHistory approvals={approvals} />
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
