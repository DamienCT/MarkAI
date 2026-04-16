"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowLeft, Eye, Edit3, Clock, CheckCircle, XCircle, Loader2, Trash2, CalendarClock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ContentEditor } from "@/components/content/ContentEditor";
import { ChannelPreview } from "@/components/content/ChannelPreview";

import { ApprovalHistory } from "@/components/approval/ApprovalHistory";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { api, API_BASE_URL, fileUrl } from "@/lib/api";
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
  const [imageCacheBust, setImageCacheBust] = useState("");
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduleTime, setScheduleTime] = useState("09:00");
  const [scheduling, setScheduling] = useState(false);

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
      } catch {
        toast.error("Failed to load content");
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

  const handleRegenerateImage = useCallback(async () => {
    if (!content) return;
    setRegeneratingImage(true);
    try {
      await api.post(`/api/v1/content/${content.id}/regenerate-image`, {
        prompt: imagePrompt || undefined,
      });
      toast.success("Image regeneration started — this may take a minute...");

      // Poll for completion: check calendar item status until it leaves "working"
      const calItemId = content.calendar_item_id;
      if (calItemId) {
        const maxAttempts = 40; // ~2 minutes
        for (let i = 0; i < maxAttempts; i++) {
          await new Promise(r => setTimeout(r, 3000));
          try {
            const calItem = await api.get<CalendarItem>(`/api/v1/calendar/${calItemId}`);
            if (calItem.status !== "working") {
              // Reload content to get the new image
              const updated = await api.get<Content>(`/api/v1/content/${content.id}`);
              setContent(updated);
              setCalendarItem(calItem);
              setImageCacheBust(`_cb=${Date.now()}`);
              toast.success("Image regenerated successfully");
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
      const scheduledAt = new Date(`${scheduleDate}T${scheduleTime}:00`).toISOString();
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

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-[600px] w-full" />
      </div>
    );
  }

  if (!content) {
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
  // Resolve image URL from generation_metadata — prefer branded (has logo+text) over raw
  const imagePath = (
    content.generation_metadata?.branded_image ||
    content.generation_metadata?.raw_image ||
    content.generation_metadata?.generated_image_url ||
    ""
  ) as string;
  const contentImageUrl = imagePath
    ? (imagePath.startsWith("http") ? imagePath : `${API_BASE_URL}/api/v1/files/${imagePath}`) + (imageCacheBust ? `?${imageCacheBust}` : "")
    : undefined;
  // Thumbnail for faster preview loading (600px wide, quality 75)
  const contentThumbUrl = contentImageUrl
    ? `${contentImageUrl}${contentImageUrl.includes("?") ? "&" : "?"}w=600&q=75`
    : undefined;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push("/content")}>
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

      <Tabs defaultValue="preview">
        <TabsList>
          <TabsTrigger value="preview" className="gap-1.5">
            <Eye className="h-3.5 w-3.5" /> Preview
          </TabsTrigger>
          <TabsTrigger value="edit" className="gap-1.5">
            <Edit3 className="h-3.5 w-3.5" /> Edit
          </TabsTrigger>
          <TabsTrigger value="history" className="gap-1.5">
            <Clock className="h-3.5 w-3.5" /> History
          </TabsTrigger>
        </TabsList>

        {/* Preview Tab */}
        <TabsContent value="preview" className="mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="flex justify-center">
              <ChannelPreview
                channel={channel}
                brandName={brandName}
                brandHandle={brandHandle}
                avatarUrl={brandAvatarUrl}
                caption={caption}
                hashtags={hashtags}
                imageUrl={contentThumbUrl || contentImageUrl}
                cta={content.cta || content.cta_text}
              />
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

              {/* Scheduled info — shown when content is auto-scheduled after approval */}
              {calendarItem && calendarItem.status === "scheduled" && calendarItem.scheduled_at && (
                <Card className="border-blue-500/30 bg-blue-500/5">
                  <CardContent className="py-3">
                    <p className="text-sm text-blue-600 dark:text-blue-400 font-medium">
                      Scheduled for publishing on {new Date(calendarItem.scheduled_at).toLocaleDateString()} at {new Date(calendarItem.scheduled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </p>
                  </CardContent>
                </Card>
              )}

              {/* Discard content — visible for in_review and reworking statuses */}
              {calendarItem && ["in_review", "reworking"].includes(calendarItem.status) && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="w-full"
                  onClick={handleDiscard}
                >
                  <Trash2 className="mr-1.5 h-4 w-4" />
                  Discard Content
                </Button>
              )}

              {/* Image regeneration */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Image</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {content.generation_metadata?.raw_image || content.generation_metadata?.generated_image_url ? (
                    <p className="text-xs text-green-600">Image generated</p>
                  ) : (
                    <p className="text-xs text-muted-foreground">No image generated yet</p>
                  )}
                  <div className="space-y-2">
                    <Textarea
                      placeholder="Custom image prompt (optional — leave blank to auto-generate from content)..."
                      value={imagePrompt}
                      onChange={(e) => setImagePrompt(e.target.value)}
                      rows={2}
                      className="text-xs"
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={regeneratingImage}
                      onClick={handleRegenerateImage}
                      className="w-full"
                    >
                      {regeneratingImage ? <><Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> Generating...</> : "Regenerate Image"}
                    </Button>
                  </div>
                </CardContent>
              </Card>

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
        <TabsContent value="edit" className="mt-6">
          <ContentEditor content={content} onSave={handleSave} />
        </TabsContent>

        {/* History Tab */}
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
      </Tabs>
    </div>
  );
}
