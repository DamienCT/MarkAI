"use client";

import React from "react";
import {
  Heart, MessageCircle, Send, Bookmark, Share2,
  ThumbsUp, MoreHorizontal, Globe, Repeat2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { sanitizeImageUrl } from "@/lib/utils";

interface PreviewProps {
  brandName: string;
  brandHandle: string;
  caption: string;
  hashtags: string[];
  imageUrl?: string;
  avatarUrl?: string;
  cta?: string;
  compact?: boolean;
}

function AvatarCircle({ name, size = "h-9 w-9", avatarUrl }: { name: string; size?: string; avatarUrl?: string }) {
  const initial = name.charAt(0).toUpperCase();
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={name}
        className={`${size} rounded-full object-cover shrink-0 bg-white`}
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

export function InstagramPreview({ brandName, brandHandle, caption, hashtags, imageUrl, avatarUrl, compact }: PreviewProps) {
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
      {/* Image */}
      {imageUrl && sanitizeImageUrl(imageUrl) ? (
        <img src={sanitizeImageUrl(imageUrl)} alt="Post" className="w-full aspect-square object-cover" />
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

export function FacebookPreview({ brandName, brandHandle, caption, hashtags, imageUrl, avatarUrl, compact }: PreviewProps) {
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
      {/* Image */}
      {imageUrl && sanitizeImageUrl(imageUrl) ? (
        <img src={sanitizeImageUrl(imageUrl)} alt="Post" className="w-full aspect-[16/9] object-cover" />
      ) : (
        <div className="w-full aspect-[16/9] bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-800 dark:to-slate-700 flex items-center justify-center">
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

export function LinkedInPreview({ brandName, brandHandle, caption, hashtags, imageUrl, avatarUrl, compact }: PreviewProps) {
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
      {/* Image */}
      {imageUrl && sanitizeImageUrl(imageUrl) ? (
        <img src={sanitizeImageUrl(imageUrl)} alt="Post" className="w-full aspect-[1.91/1] object-cover" />
      ) : (
        <div className="w-full aspect-[1.91/1] bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-800 dark:to-slate-700 flex items-center justify-center">
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

export function XPreview({ brandName, brandHandle, caption, hashtags, imageUrl, avatarUrl, compact }: PreviewProps) {
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
          {/* Image */}
          {imageUrl ? (
            <img src={imageUrl} alt="Post" className="w-full rounded-xl mt-2 border aspect-[16/9] object-cover" />
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
      return <FacebookPreview {...props} />; // YouTube uses a similar layout
    default:
      return <InstagramPreview {...props} />; // Default to Instagram-style
  }
}
