// ── Consolidated display constants ──────────────────────────────────
// Single source of truth for channel names, colors, and status colors.

export const CHANNEL_DISPLAY_NAMES: Record<string, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  youtube: "YouTube",
  tiktok: "TikTok",
  x: "X (Twitter)",
  website_blog: "Website / Blog",
  teams: "Teams",
};

export const CHANNEL_COLORS: Record<string, string> = {
  instagram: "bg-pink-100 text-pink-700 dark:bg-pink-900 dark:text-pink-300",
  facebook: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  linkedin: "bg-sky-100 text-sky-700 dark:bg-sky-900 dark:text-sky-300",
  youtube: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
  tiktok: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  x: "bg-zinc-100 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-300",
  website_blog: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  teams: "bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300",
};

export const STATUS_COLORS: Record<string, string> = {
  planned: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200",
  queued: "bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-200",
  working: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200",
  in_review: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  reworking: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  rendering: "bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-900 dark:text-fuchsia-200",
  approved: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200",
  scheduled: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  publishing: "bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-200",
  published: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};
