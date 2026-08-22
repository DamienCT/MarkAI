"use client";

import React, { useCallback, useEffect, useState, useMemo } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { api, isAuthError } from "@/lib/api";
import { useRequireRole } from "@/lib/hooks";

/* -- IANA timezone helpers ---------------------------------------- */

function getAllTimezones(): string[] {
  try {
    if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
      return (Intl as unknown as { supportedValuesOf: (key: string) => string[] }).supportedValuesOf("timeZone");
    }
  } catch {
    // fallback below
  }
  return [
    "Africa/Abidjan", "Africa/Accra", "Africa/Addis_Ababa", "Africa/Algiers",
    "Africa/Cairo", "Africa/Casablanca", "Africa/Dar_es_Salaam", "Africa/Johannesburg",
    "Africa/Lagos", "Africa/Nairobi", "Africa/Tunis",
    "America/Anchorage", "America/Argentina/Buenos_Aires", "America/Bogota",
    "America/Chicago", "America/Denver", "America/Halifax", "America/Lima",
    "America/Los_Angeles", "America/Mexico_City", "America/New_York",
    "America/Phoenix", "America/Santiago", "America/Sao_Paulo", "America/Toronto",
    "America/Vancouver",
    "Asia/Baghdad", "Asia/Bangkok", "Asia/Colombo", "Asia/Dhaka", "Asia/Dubai",
    "Asia/Hong_Kong", "Asia/Istanbul", "Asia/Jakarta", "Asia/Karachi",
    "Asia/Kolkata", "Asia/Kuala_Lumpur", "Asia/Manila", "Asia/Riyadh",
    "Asia/Seoul", "Asia/Shanghai", "Asia/Singapore", "Asia/Taipei",
    "Asia/Tehran", "Asia/Tokyo",
    "Atlantic/Reykjavik",
    "Australia/Adelaide", "Australia/Brisbane", "Australia/Darwin",
    "Australia/Melbourne", "Australia/Perth", "Australia/Sydney",
    "Europe/Amsterdam", "Europe/Athens", "Europe/Belgrade", "Europe/Berlin",
    "Europe/Brussels", "Europe/Bucharest", "Europe/Budapest", "Europe/Copenhagen",
    "Europe/Dublin", "Europe/Helsinki", "Europe/Kiev", "Europe/Lisbon",
    "Europe/London", "Europe/Madrid", "Europe/Moscow", "Europe/Oslo",
    "Europe/Paris", "Europe/Prague", "Europe/Rome", "Europe/Stockholm",
    "Europe/Vienna", "Europe/Warsaw", "Europe/Zurich",
    "Indian/Maldives", "Indian/Mauritius",
    "Pacific/Auckland", "Pacific/Fiji", "Pacific/Guam", "Pacific/Honolulu",
    "Pacific/Tahiti", "Pacific/Tongatapu",
    "UTC",
  ];
}

function groupTimezones(timezones: string[]): Record<string, string[]> {
  const groups: Record<string, string[]> = {};
  for (const tz of timezones) {
    const slash = tz.indexOf("/");
    const region = slash > -1 ? tz.substring(0, slash) : "Other";
    if (!groups[region]) groups[region] = [];
    groups[region].push(tz);
  }
  const sorted: Record<string, string[]> = {};
  for (const region of Object.keys(groups).sort()) {
    sorted[region] = groups[region].sort();
  }
  return sorted;
}

/* -- Types -------------------------------------------------------- */

interface AppSettings {
  scheduler_timezone: string;
  morning_schedule_hour: number;
  morning_schedule_minute: number;
  publish_check_interval_minutes: number;
  engagement_pull_interval_hours: number;
  bc_sync_interval_hours: number;
  max_daily_posts: number;
  auto_approve_threshold: number;
  content_generation_days_ahead: number;
  default_channels: string[];
  notification_channels: string[];
}

const DEFAULTS: AppSettings = {
  scheduler_timezone: "Indian/Mauritius",
  morning_schedule_hour: 6,
  morning_schedule_minute: 0,
  publish_check_interval_minutes: 15,
  engagement_pull_interval_hours: 6,
  bc_sync_interval_hours: 6,
  max_daily_posts: 3,
  auto_approve_threshold: 90,
  content_generation_days_ahead: 7,
  default_channels: ["instagram", "facebook", "linkedin"],
  notification_channels: ["teams", "portal"],
};

/* -- Component ---------------------------------------------------- */

export default function SettingsPage() {
  useRequireRole("manager"); // redirects unauthorized users as a side effect
  const [settings, setSettings] = useState<AppSettings>(DEFAULTS);
  const [loading, setLoading] = useState(true);
  // Fail closed (UX-01): until the authoritative read succeeds at least once,
  // the form only shows DEFAULTS — saving then would overwrite the real
  // scheduler config with defaults, so Save stays disabled while this is true.
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tzSearch, setTzSearch] = useState("");

  const allTimezones = useMemo(() => getAllTimezones(), []);
  const groupedTimezones = useMemo(() => groupTimezones(allTimezones), [allTimezones]);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const data = await api.get<Record<string, unknown>>("/api/v1/settings");
      setSettings({
        scheduler_timezone: (data.scheduler_timezone as string) ?? DEFAULTS.scheduler_timezone,
        morning_schedule_hour: Number(data.morning_schedule_hour ?? DEFAULTS.morning_schedule_hour),
        morning_schedule_minute: Number(data.morning_schedule_minute ?? DEFAULTS.morning_schedule_minute),
        publish_check_interval_minutes: Number(data.publish_check_interval_minutes ?? DEFAULTS.publish_check_interval_minutes),
        engagement_pull_interval_hours: Number(data.engagement_pull_interval_hours ?? DEFAULTS.engagement_pull_interval_hours),
        bc_sync_interval_hours: Number(data.bc_sync_interval_hours ?? DEFAULTS.bc_sync_interval_hours),
        max_daily_posts: Number(data.max_daily_posts ?? DEFAULTS.max_daily_posts),
        auto_approve_threshold: Number(data.auto_approve_threshold ?? DEFAULTS.auto_approve_threshold),
        content_generation_days_ahead: Number(data.content_generation_days_ahead ?? DEFAULTS.content_generation_days_ahead),
        default_channels: (data.default_channels as string[]) ?? DEFAULTS.default_channels,
        notification_channels: (data.notification_channels as string[]) ?? DEFAULTS.notification_channels,
      });
    } catch (err) {
      setLoadFailed(true);
      // Session expiry: the sign-in redirect is already underway.
      if (!isAuthError(err)) toast.error("Failed to load settings — showing defaults (read-only)");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const handleSave = async () => {
    if (loadFailed) return; // never overwrite real config with defaults
    setSaving(true);
    try {
      await api.put("/api/v1/settings", settings);
      toast.success("Settings saved successfully");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to save settings";
      toast.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const toggleChannel = (key: "default_channels" | "notification_channels", channel: string) => {
    setSettings((s) => {
      const current = s[key];
      const next = current.includes(channel)
        ? current.filter((c) => c !== channel)
        : [...current, channel];
      return { ...s, [key]: next };
    });
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Settings</h1>
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold">Settings</h1>
          <p className="text-muted-foreground">Global application configuration</p>
        </div>
        <Button
          onClick={handleSave}
          disabled={saving || loadFailed}
          size="default"
          title={loadFailed ? "Saving is disabled while settings could not be loaded" : undefined}
        >
          {saving ? "Saving..." : "Save Settings"}
        </Button>
      </div>

      {loadFailed && (
        <div className="flex items-center justify-between flex-wrap gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950">
          <p className="text-sm text-amber-800 dark:text-amber-200">
            Showing defaults — the saved settings could not be loaded. Saving is
            disabled so the real configuration is not overwritten; reload to edit.
          </p>
          <Button variant="outline" size="sm" onClick={fetchSettings}>
            Retry
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

      {/* -- Row 1: Timezone | Scheduler -- */}
      <Card>
        <CardHeader>
          <CardTitle>Timezone</CardTitle>
          <CardDescription>Select the primary timezone for scheduling</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label htmlFor="tz-region">Region</Label>
          <select
            id="tz-region"
            value={tzSearch || settings.scheduler_timezone.split("/")[0]}
            onChange={(e) => setTzSearch(e.target.value)}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring [&>option]:bg-background [&>option]:text-foreground"
          >
            {Object.keys(groupedTimezones).map((region) => (
              <option key={region} value={region}>{region}</option>
            ))}
          </select>
          <Label htmlFor="tz-select">Timezone</Label>
          <select
            id="tz-select"
            value={settings.scheduler_timezone}
            onChange={(e) => setSettings((s) => ({ ...s, scheduler_timezone: e.target.value }))}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring [&>option]:bg-background [&>option]:text-foreground"
          >
            {(groupedTimezones[tzSearch || settings.scheduler_timezone.split("/")[0]] || []).map((tz) => (
              <option key={tz} value={tz}>
                {tz.split("/").slice(1).join("/").replace(/_/g, " ") || tz}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            Current: <span className="font-medium">{settings.scheduler_timezone}</span>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scheduler Settings</CardTitle>
          <CardDescription>Configure scheduling intervals and morning schedule</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="morning-hour">Morning Schedule Hour</Label>
              <select
                id="morning-hour"
                value={settings.morning_schedule_hour}
                onChange={(e) => setSettings((s) => ({ ...s, morning_schedule_hour: Number(e.target.value) }))}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              >
                {Array.from({ length: 24 }, (_, i) => (
                  <option key={i} value={i}>{String(i).padStart(2, "0")}:00</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="morning-minute">Morning Schedule Minute</Label>
              <select
                id="morning-minute"
                value={settings.morning_schedule_minute}
                onChange={(e) => setSettings((s) => ({ ...s, morning_schedule_minute: Number(e.target.value) }))}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              >
                {[0, 15, 30, 45].map((m) => (
                  <option key={m} value={m}>:{String(m).padStart(2, "0")}</option>
                ))}
              </select>
            </div>
          </div>

          <Separator />

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="publish-interval">Publish Check Interval</Label>
              <select
                id="publish-interval"
                value={settings.publish_check_interval_minutes}
                onChange={(e) => setSettings((s) => ({ ...s, publish_check_interval_minutes: Number(e.target.value) }))}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              >
                {[5, 10, 15, 30, 60].map((m) => (
                  <option key={m} value={m}>{m} minutes</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="engagement-interval">Engagement Pull Interval</Label>
              <select
                id="engagement-interval"
                value={settings.engagement_pull_interval_hours}
                onChange={(e) => setSettings((s) => ({ ...s, engagement_pull_interval_hours: Number(e.target.value) }))}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              >
                {[1, 2, 4, 6, 12, 24].map((h) => (
                  <option key={h} value={h}>{h} {h === 1 ? "hour" : "hours"}</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="bc-sync-interval">BC Sync Interval</Label>
              <select
                id="bc-sync-interval"
                value={settings.bc_sync_interval_hours}
                onChange={(e) => setSettings((s) => ({ ...s, bc_sync_interval_hours: Number(e.target.value) }))}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
              >
                {[1, 2, 4, 6, 12, 24].map((h) => (
                  <option key={h} value={h}>{h} {h === 1 ? "hour" : "hours"}</option>
                ))}
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* -- Row 2: Auto-Approve Threshold | Max Daily Posts -- */}
      <Card>
        <CardHeader>
          <CardTitle>Auto-Approve Threshold</CardTitle>
          <CardDescription>Content with AI confidence above this threshold will be auto-approved</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={80}
              max={100}
              step={1}
              value={settings.auto_approve_threshold}
              onChange={(e) => setSettings((s) => ({ ...s, auto_approve_threshold: Number(e.target.value) }))}
              className="flex-1 h-2 accent-primary cursor-pointer"
            />
            <span className="text-lg font-semibold w-14 text-right tabular-nums">
              {settings.auto_approve_threshold}%
            </span>
          </div>
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>80%</span>
            <span>100%</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Max Daily Posts Per Channel</CardTitle>
          <CardDescription>Maximum posts to publish per channel per day</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-3">
            {[1, 2, 3, 4, 5, 6, 8, 10].map((n) => (
              <label
                key={n}
                className={`flex items-center justify-center w-14 h-10 rounded-md border cursor-pointer text-sm font-medium transition-colors ${
                  settings.max_daily_posts === n
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background text-foreground border-input hover:bg-accent"
                }`}
              >
                <input
                  type="radio"
                  name="max_daily_posts"
                  value={n}
                  checked={settings.max_daily_posts === n}
                  onChange={() => setSettings((s) => ({ ...s, max_daily_posts: n }))}
                  className="sr-only"
                />
                {n}
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* -- Row 2b: Content Queue Window -- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Content Queue Window</CardTitle>
          <CardDescription>How many days ahead to generate content for</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <Input
              type="number"
              min={1}
              max={30}
              value={settings.content_generation_days_ahead}
              onChange={(e) => setSettings(s => ({ ...s, content_generation_days_ahead: Number(e.target.value) || 7 }))}
              className="w-20"
            />
            <span className="text-sm text-muted-foreground">days</span>
          </div>
        </CardContent>
      </Card>

      {/* -- Row 3: Default Channels | Notification Channels -- */}
      <Card>
        <CardHeader>
          <CardTitle>Default Channels</CardTitle>
          <CardDescription>Channels enabled by default for new content</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { value: "instagram", label: "Instagram" },
              { value: "facebook", label: "Facebook" },
              { value: "linkedin", label: "LinkedIn" },
              { value: "youtube", label: "YouTube" },
              { value: "tiktok", label: "TikTok" },
              { value: "x", label: "X (Twitter)" },
              { value: "website_blog", label: "Blog" },
              { value: "teams", label: "Teams" },
            ].map(({ value, label }) => (
              <label key={value} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.default_channels.includes(value)}
                  onChange={() => toggleChannel("default_channels", value)}
                  className="h-4 w-4 rounded-sm border-input accent-primary"
                />
                <span className="text-sm font-medium">{label}</span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Notification Channels</CardTitle>
          <CardDescription>Where notifications are delivered</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[
              { value: "teams", label: "Teams", desc: "Alerts via Microsoft Teams webhook" },
              { value: "portal", label: "In-App Portal", desc: "Real-time notifications in the app" },
            ].map(({ value, label, desc }) => (
              <label key={value} className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.notification_channels.includes(value)}
                  onChange={() => toggleChannel("notification_channels", value)}
                  className="h-4 w-4 rounded-sm border-input accent-primary shrink-0"
                />
                <span className="text-sm font-medium">{label}</span>
                <span className="text-xs text-muted-foreground">{desc}</span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      </div>{/* end grid */}
    </div>
  );
}
