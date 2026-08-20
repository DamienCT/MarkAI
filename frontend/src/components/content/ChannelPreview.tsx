"use client";

import React, { useEffect, useState } from "react";
import {
  Heart, MessageCircle, Send, Bookmark, Share2,
  ThumbsUp, MoreHorizontal, Globe, Repeat2, X, Youtube,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { sanitizeImageUrl } from "@/lib/utils";

/** Image that opens a full-screen lightbox on click. Used by every channel
 *  preview so the user can inspect the actual rendered image (with overlay
 *  + logo) at full resolution instead of squinting at the small thumbnail. */
function ClickableImage({
  src,
  alt,
  className,
  overlay,
}: {
  src: string;
  alt: string;
  className?: string;
  /** Rendered at the image's top-right, revealed on hover over the image. */
  overlay?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  // Close the lightbox on Escape so users don't have to hunt for the X.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    // Prevent body scroll while the lightbox is open
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open]);

  return (
    <>
      <div className="relative group/img">
        <img
          src={src}
          alt={alt}
          loading="lazy"
          className={`${className || ""} cursor-zoom-in`}
          onClick={() => setOpen(true)}
        />
        {overlay ? (
          <div className="absolute right-2 top-2 z-10 opacity-0 transition-opacity duration-150 group-hover/img:opacity-100 focus-within:opacity-100">
            {overlay}
          </div>
        ) : null}
      </div>
      {open && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-4"
          onClick={() => setOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Image preview"
        >
          <button
            type="button"
            className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20 transition-colors"
            aria-label="Close preview"
            onClick={(e) => { e.stopPropagation(); setOpen(false); }}
          >
            <X className="h-5 w-5" />
          </button>
          <img
            src={src}
            alt={alt}
            className="max-h-[90vh] max-w-[95vw] object-contain rounded-md shadow-2xl cursor-zoom-out"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}

interface PreviewProps {
  brandName: string;
  brandHandle: string;
  caption: string;
  hashtags: string[];
  imageUrl?: string;
  /** Rendered reel video — when set, the media slot shows a player instead of the image. */
  videoUrl?: string;
  avatarUrl?: string;
  cta?: string;
  compact?: boolean;
  /** Optional control overlaid on the post image (revealed on hover). */
  imageOverlay?: React.ReactNode;
}

/** Video rendered in a preview's media slot (reels). Reels are 9:16 portrait;
 *  the keyframe image doubles as the poster so the frame isn't black before
 *  playback starts. */
function MediaVideo({ src, poster, className }: { src: string; poster?: string; className?: string }) {
  return (
    <video
      src={src}
      poster={poster ? sanitizeImageUrl(poster) || undefined : undefined}
      controls
      playsInline
      preload="metadata"
      className={className || "w-full aspect-[9/16] object-cover bg-black"}
    />
  );
}

function AvatarCircle({ name, size = "h-9 w-9", avatarUrl }: { name: string; size?: string; avatarUrl?: string }) {
  const initial = name.charAt(0).toUpperCase();
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={name}
        className={`${size} rounded-full object-contain shrink-0 bg-white border p-0.5`}
      />
    );
  }
  return (
    <div className={`${size} rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center text-white font-bold text-sm shrink-0`}>
      {initial}
    </div>
  );
}

function ImagePlaceholder() {
  return (
    <div className="w-full aspect-square bg-gradient-to-br from-slate-100 via-slate-50 to-slate-200 dark:from-slate-800 dark:via-slate-700 dark:to-slate-800 flex items-center justify-center">
      <div className="text-center text-muted-foreground">
        <Globe className="h-10 w-10 mx-auto mb-2 opacity-30" />
        <p className="text-xs opacity-50">Image preview</p>
      </div>
    </div>
  );
}

function HashtagsDisplay({ hashtags }: { hashtags: string[] }) {
  if (!hashtags.length) return null;
  return (
    <p className="text-xs text-blue-500 dark:text-blue-400 mt-1">
      {hashtags.slice(0, 10).map((h) => `#${h}`).join(" ")}
      {hashtags.length > 10 && " ..."}
    </p>
  );
}

export function InstagramPreview({ brandName, brandHandle, caption, hashtags, imageUrl, videoUrl, avatarUrl, compact, imageOverlay }: PreviewProps) {
  return (
    <div className="bg-white dark:bg-zinc-900 rounded-xl border shadow-sm max-w-[400px] mx-auto overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <AvatarCircle name={brandName} avatarUrl={avatarUrl} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold truncate">{brandHandle}</p>
          <p className="text-[10px] text-muted-foreground">Sponsored</p>
        </div>
        <MoreHorizontal className="h-5 w-5 text-muted-foreground" />
      </div>
      {/* Media — reel video (9:16) when rendered, otherwise the post image */}
      {videoUrl ? (
        <MediaVideo src={videoUrl} poster={imageUrl} />
      ) : imageUrl && sanitizeImageUrl(imageUrl) ? (
        <ClickableImage src={sanitizeImageUrl(imageUrl)} alt="Post" className="w-full aspect-square object-cover" overlay={imageOverlay} />
      ) : (
        <ImagePlaceholder />
      )}
      {/* Actions */}
      <div className="px-3 pt-2.5 pb-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Heart className="h-6 w-6 cursor-pointer hover:text-red-500 transition-colors" />
            <MessageCircle className="h-6 w-6 cursor-pointer" />
            <Send className="h-6 w-6 cursor-pointer" />
          </div>
          <Bookmark className="h-6 w-6 cursor-pointer" />
        </div>
        <p className="text-xs font-semibold mt-2">1,247 likes</p>
      </div>
      {/* Caption */}
      <div className="px-3 pb-3">
        <p className={`text-xs whitespace-pre-wrap ${compact ? "line-clamp-3" : ""}`}>
          <span className="font-semibold mr-1">{brandHandle}</span>
          {caption}
        </p>
        <HashtagsDisplay hashtags={hashtags} />
      </div>
    </div>
  );
}

export function FacebookPreview({ brandName, brandHandle, caption, hashtags, imageUrl, videoUrl, avatarUrl, compact, imageOverlay }: PreviewProps) {
  return (
    <div className="bg-white dark:bg-zinc-900 rounded-xl border shadow-sm max-w-[400px] mx-auto overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-3 py-3">
        <AvatarCircle name={brandName} avatarUrl={avatarUrl} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold truncate">{brandName}</p>
          <p className="text-[10px] text-muted-foreground flex items-center gap-1">
            Just now <Globe className="h-2.5 w-2.5" />
          </p>
        </div>
        <MoreHorizontal className="h-5 w-5 text-muted-foreground" />
      </div>
      {/* Caption */}
      <div className="px-3 pb-2">
        <p className={`text-sm whitespace-pre-wrap ${compact ? "line-clamp-3" : ""}`}>{caption}</p>
        <HashtagsDisplay hashtags={hashtags} />
      </div>
      {/* Media — reel video (9:16) when rendered; otherwise the image whose
          aspect matches the actual generated landscape (1536x1024 = 3:2).
          A previous 16:9 mask center-cropped 80px top/bottom and clipped the
          text card whose anchor sits 4% above the image bottom. */}
      {videoUrl ? (
        <MediaVideo src={videoUrl} poster={imageUrl} />
      ) : imageUrl && sanitizeImageUrl(imageUrl) ? (
        <ClickableImage src={sanitizeImageUrl(imageUrl)} alt="Post" className="w-full aspect-[3/2] object-cover" overlay={imageOverlay} />
      ) : (
        <div className="w-full aspect-[3/2] bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-800 dark:to-slate-700 flex items-center justify-center">
          <Globe className="h-10 w-10 opacity-20" />
        </div>
      )}
      {/* Reactions */}
      <div className="px-3 py-2 border-t">
        <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
          <span>42 reactions</span>
          <span>8 comments</span>
        </div>
        <div className="flex items-center justify-around border-t pt-2">
          <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-blue-500 transition-colors py-1">
            <ThumbsUp className="h-4 w-4" /> Like
          </button>
          <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-blue-500 transition-colors py-1">
            <MessageCircle className="h-4 w-4" /> Comment
          </button>
          <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-blue-500 transition-colors py-1">
            <Share2 className="h-4 w-4" /> Share
          </button>
        </div>
      </div>
    </div>
  );
}

export function LinkedInPreview({ brandName, brandHandle, caption, hashtags, imageUrl, videoUrl, avatarUrl, compact, imageOverlay }: PreviewProps) {
  return (
    <div className="bg-white dark:bg-zinc-900 rounded-xl border shadow-sm max-w-[400px] mx-auto overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-3 py-3">
        <AvatarCircle name={brandName} avatarUrl={avatarUrl} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold truncate">{brandName}</p>
          <p className="text-[10px] text-muted-foreground">Company &middot; Just now</p>
        </div>
        <MoreHorizontal className="h-5 w-5 text-muted-foreground" />
      </div>
      {/* Caption */}
      <div className="px-3 pb-2">
        <p className={`text-sm leading-relaxed whitespace-pre-wrap ${compact ? "line-clamp-4" : ""}`}>{caption}</p>
        <HashtagsDisplay hashtags={hashtags} />
      </div>
      {/* Media — reel video (9:16) when rendered; otherwise the image matching
          the actual generated landscape ratio (1536x1024 = 3:2). LinkedIn's
          link-preview spec is 1.91:1 but our images are generated at 3:2;
          cropping to 1.91:1 here clips the bottom of the text card. */}
      {videoUrl ? (
        <MediaVideo src={videoUrl} poster={imageUrl} />
      ) : imageUrl && sanitizeImageUrl(imageUrl) ? (
        <ClickableImage src={sanitizeImageUrl(imageUrl)} alt="Post" className="w-full aspect-[3/2] object-cover" overlay={imageOverlay} />
      ) : (
        <div className="w-full aspect-[3/2] bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-800 dark:to-slate-700 flex items-center justify-center">
          <Globe className="h-10 w-10 opacity-20" />
        </div>
      )}
      {/* Reactions */}
      <div className="px-3 py-2 border-t">
        <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
          <span>156 reactions</span>
          <span>12 comments &middot; 3 reposts</span>
        </div>
        <div className="flex items-center justify-around border-t pt-2">
          <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-blue-600 transition-colors py-1">
            <ThumbsUp className="h-4 w-4" /> Like
          </button>
          <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-blue-600 transition-colors py-1">
            <MessageCircle className="h-4 w-4" /> Comment
          </button>
          <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-blue-600 transition-colors py-1">
            <Repeat2 className="h-4 w-4" /> Repost
          </button>
          <button className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-blue-600 transition-colors py-1">
            <Send className="h-4 w-4" /> Send
          </button>
        </div>
      </div>
    </div>
  );
}

export function XPreview({ brandName, brandHandle, caption, hashtags, imageUrl, videoUrl, avatarUrl, compact, imageOverlay }: PreviewProps) {
  const handle = brandHandle.startsWith("@") ? brandHandle : `@${brandHandle}`;
  return (
    <div className="bg-white dark:bg-zinc-900 rounded-xl border shadow-sm max-w-[400px] mx-auto overflow-hidden">
      <div className="flex gap-2.5 px-3 py-3">
        <AvatarCircle name={brandName} avatarUrl={avatarUrl} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1">
            <span className="text-sm font-bold truncate">{brandName}</span>
            <span className="text-xs text-muted-foreground truncate">{handle}</span>
            <span className="text-xs text-muted-foreground">&middot; now</span>
          </div>
          <p className={`text-sm mt-1 whitespace-pre-wrap ${compact ? "line-clamp-4" : ""}`}>{caption}</p>
          <HashtagsDisplay hashtags={hashtags} />
          {/* Media — reel video (9:16) when rendered, otherwise the image */}
          {videoUrl ? (
            <MediaVideo src={videoUrl} poster={imageUrl} className="w-full rounded-xl mt-2 border aspect-[9/16] object-cover bg-black" />
          ) : imageUrl ? (
            <ClickableImage src={imageUrl} alt="Post" className="w-full rounded-xl mt-2 border aspect-[16/9] object-cover" overlay={imageOverlay} />
          ) : (
            <div className="w-full rounded-xl mt-2 border aspect-[16/9] bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-800 dark:to-slate-700 flex items-center justify-center">
              <Globe className="h-8 w-8 opacity-20" />
            </div>
          )}
          {/* Engagement */}
          <div className="flex items-center justify-between mt-3 text-muted-foreground">
            <button className="flex items-center gap-1 text-xs hover:text-blue-500 transition-colors">
              <MessageCircle className="h-4 w-4" /> 12
            </button>
            <button className="flex items-center gap-1 text-xs hover:text-green-500 transition-colors">
              <Repeat2 className="h-4 w-4" /> 8
            </button>
            <button className="flex items-center gap-1 text-xs hover:text-red-500 transition-colors">
              <Heart className="h-4 w-4" /> 89
            </button>
            <button className="flex items-center gap-1 text-xs hover:text-blue-500 transition-colors">
              <Bookmark className="h-4 w-4" />
            </button>
            <button className="flex items-center gap-1 text-xs hover:text-blue-500 transition-colors">
              <Share2 className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** YouTube Shorts-style frame: dark chrome, 9:16 video, channel + caption
 *  overlaid on the player like the real Shorts UI. Used for youtube reels. */
export function YouTubeShortsPreview({ brandName, brandHandle, caption, hashtags, imageUrl, videoUrl, avatarUrl, compact }: PreviewProps) {
  return (
    <div className="bg-black rounded-xl border shadow-sm max-w-[300px] mx-auto overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-white">
          <Youtube className="h-4 w-4 text-red-500" /> Shorts
        </p>
        <MoreHorizontal className="h-5 w-5 text-white/70" />
      </div>
      {/* Video */}
      <div className="relative">
        {videoUrl ? (
          <MediaVideo src={videoUrl} poster={imageUrl} />
        ) : (
          <div className="w-full aspect-[9/16] bg-gradient-to-br from-zinc-800 to-zinc-900 flex items-center justify-center">
            <Globe className="h-10 w-10 opacity-20 text-white" />
          </div>
        )}
        {/* Overlay: channel + caption bottom-left, action rail on the right.
            pointer-events-none keeps the native <video> controls clickable;
            bottom offset clears the controls bar. */}
        <div className="absolute inset-x-0 bottom-14 flex items-end justify-between px-3 pointer-events-none">
          <div className="min-w-0 pr-2 text-white drop-shadow">
            <div className="flex items-center gap-1.5 mb-1">
              <AvatarCircle name={brandName} size="h-6 w-6" avatarUrl={avatarUrl} />
              <span className="text-xs font-semibold truncate">@{brandHandle}</span>
            </div>
            <p className={`text-xs whitespace-pre-wrap ${compact ? "line-clamp-2" : "line-clamp-3"}`}>{caption}</p>
            <HashtagsDisplay hashtags={hashtags} />
          </div>
          <div className="flex flex-col items-center gap-3 text-white shrink-0">
            <ThumbsUp className="h-5 w-5" />
            <MessageCircle className="h-5 w-5" />
            <Share2 className="h-5 w-5" />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Auto-selects the right preview based on channel */
export function ChannelPreview({
  channel,
  ...props
}: PreviewProps & { channel: string }) {
  switch (channel) {
    case "instagram":
      return <InstagramPreview {...props} />;
    case "facebook":
      return <FacebookPreview {...props} />;
    case "linkedin":
      return <LinkedInPreview {...props} />;
    case "x":
      return <XPreview {...props} />;
    case "youtube":
      // Reels get the Shorts frame; regular posts keep the FB-style layout
      return props.videoUrl ? <YouTubeShortsPreview {...props} /> : <FacebookPreview {...props} />;
    default:
      return <InstagramPreview {...props} />; // Default to Instagram-style
  }
}
