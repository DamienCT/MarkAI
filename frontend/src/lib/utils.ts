import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { format, formatDistanceToNow, parseISO } from "date-fns";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(dateString: string): string {
  try {
    return format(parseISO(dateString), "MMM d, yyyy");
  } catch {
    return dateString;
  }
}

export function formatDateTime(dateString: string): string {
  try {
    return format(parseISO(dateString), "MMM d, yyyy h:mm a");
  } catch {
    return dateString;
  }
}

export function formatRelativeTime(dateString: string): string {
  try {
    return formatDistanceToNow(parseISO(dateString), { addSuffix: true });
  } catch {
    return dateString;
  }
}

export function statusColor(status: string): string {
  const map: Record<string, string> = {
    active: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    inactive: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
    queued: "bg-slate-100 text-slate-800 dark:bg-slate-900 dark:text-slate-300",
    working: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-300",
    in_review: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300",
    reworking: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300",
    approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-300",
    scheduled: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-300",
    publishing: "bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-300",
    published: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300",
    healthy: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    degraded: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300",
    down: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300",
    running: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300",
    completed: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300",
  };
  if (!status) return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
  return map[status.toLowerCase()] || "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
}

export function platformIcon(platform: string): string {
  const map: Record<string, string> = {
    instagram: "Instagram",
    facebook: "Facebook",
    twitter: "Twitter",
    linkedin: "Linkedin",
    tiktok: "Music2",
    youtube: "Youtube",
  };
  return map[platform.toLowerCase()] || "Globe";
}
