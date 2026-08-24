"use client";

import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, isAuthError } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";
import {
  ALL_CHANNELS,
  CHANNEL_DISPLAY_NAMES,
  type Brand,
  type Channel,
  type KillSwitchState,
  type ScopedKillSwitchFlag,
} from "@/types";
import { PauseCircle, PlayCircle, ShieldAlert } from "lucide-react";

const KILL_SWITCH_PATH = "/api/v1/system/publishing-kill-switch";

/** Decode a scoped flag key into a human label + the PUT payload scope. */
export function parseScopeKey(
  key: string,
  brandNames: Record<string, string>
): { label: string; scope: { brand_id?: string; channel?: string } } {
  const brandMatch = key.match(/^publishing_enabled:brand:(.+)$/);
  if (brandMatch) {
    const id = brandMatch[1];
    return {
      label: `Brand: ${brandNames[id] || id.slice(0, 8)}`,
      scope: { brand_id: id },
    };
  }
  const channelMatch = key.match(/^publishing_enabled:channel:(.+)$/);
  if (channelMatch) {
    const channel = channelMatch[1];
    return {
      label: `Channel: ${CHANNEL_DISPLAY_NAMES[channel as Channel] || channel}`,
      scope: { channel },
    };
  }
  return { label: key, scope: {} };
}

interface PendingChange {
  enabled: boolean;
  scope?: { brand_id?: string; channel?: string };
  label: string;
}

export function PublishingControls({ brands }: { brands: Brand[] }) {
  const [state, setState] = useState<KillSwitchState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [scopeType, setScopeType] = useState<"channel" | "brand">("channel");
  const [scopeValue, setScopeValue] = useState<string>("");

  const brandNames = brands.reduce<Record<string, string>>((acc, b) => {
    acc[b.id] = b.name;
    return acc;
  }, {});

  const refresh = useCallback(async () => {
    try {
      const data = await api.get<KillSwitchState>(KILL_SWITCH_PATH);
      setState(data);
    } catch (err) {
      if (!isAuthError(err)) toast.error("Failed to load publishing state");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const applyChange = async (change: PendingChange) => {
    setSaving(true);
    try {
      await api.put(KILL_SWITCH_PATH, {
        enabled: change.enabled,
        ...(change.scope || {}),
      });
      toast.success(
        change.enabled
          ? `Publishing resumed — ${change.label}`
          : `Publishing paused — ${change.label}`
      );
      await refresh();
    } catch (err) {
      if (!isAuthError(err)) {
        const detail =
          err && typeof err === "object" && "detail" in err
            ? String((err as { detail: unknown }).detail)
            : "request failed";
        toast.error(`Could not update publishing: ${detail}`);
      }
      throw err; // keep the confirm dialog open on failure
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <Skeleton className="h-24" />;
  }

  if (!state) {
    return (
      <p className="text-sm text-muted-foreground">
        Publishing state unavailable.
      </p>
    );
  }

  const scopedFlags: ScopedKillSwitchFlag[] = state.scoped ?? [];
  const pausedScopes = scopedFlags.filter((f) => !f.enabled);

  return (
    <div className="space-y-4">
      {/* Global switch */}
      <div className="flex items-center justify-between rounded-md border p-4">
        <div className="flex items-center gap-3 min-w-0">
          {state.enabled ? (
            <PlayCircle className="h-6 w-6 text-green-600 dark:text-green-400 shrink-0" />
          ) : (
            <PauseCircle className="h-6 w-6 text-amber-600 dark:text-amber-400 shrink-0" />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-sm font-medium">Global publishing</p>
              <Badge
                variant="outline"
                className={
                  state.enabled
                    ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300"
                    : "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300"
                }
              >
                {state.enabled ? "enabled" : "paused"}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground truncate">
              {state.enabled
                ? "Scheduled content publishes to its channels when due."
                : "All external publishing is blocked; due items wait untouched."}
              {state.updated_by && (
                <>
                  {" "}
                  Last changed by {state.updated_by}
                  {state.updated_at &&
                    ` ${formatRelativeTime(state.updated_at)}`}
                  .
                </>
              )}
            </p>
          </div>
        </div>
        <Switch
          checked={state.enabled}
          disabled={saving}
          aria-label="Global publishing"
          onCheckedChange={(next) =>
            setPending({ enabled: next, label: "all brands and channels" })
          }
        />
      </div>

      {/* Scoped overrides */}
      <div>
        <p className="text-sm font-medium mb-2">Scoped pauses</p>
        {pausedScopes.length === 0 ? (
          <p className="text-xs text-muted-foreground mb-2">
            No brand or channel is individually paused.
          </p>
        ) : (
          <div className="space-y-2 mb-2">
            {pausedScopes.map((flag) => {
              const { label, scope } = parseScopeKey(flag.key, brandNames);
              return (
                <div
                  key={flag.key}
                  className="flex items-center justify-between rounded-md border p-3 gap-3"
                >
                  <div className="min-w-0">
                    <p className="text-sm truncate">{label}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      Paused
                      {flag.updated_by && ` by ${flag.updated_by}`}
                      {flag.updated_at &&
                        ` ${formatRelativeTime(flag.updated_at)}`}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={saving}
                    onClick={() =>
                      setPending({ enabled: true, scope, label })
                    }
                  >
                    Resume
                  </Button>
                </div>
              );
            })}
          </div>
        )}

        {/* Add a scoped pause */}
        <div className="flex items-center gap-2 flex-wrap">
          <Select
            value={scopeType}
            onValueChange={(v) => {
              setScopeType(v as "channel" | "brand");
              setScopeValue("");
            }}
          >
            <SelectTrigger className="w-[120px] h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="channel">Channel</SelectItem>
              <SelectItem value="brand">Brand</SelectItem>
            </SelectContent>
          </Select>
          <Select value={scopeValue} onValueChange={setScopeValue}>
            <SelectTrigger className="w-[200px] h-8 text-xs">
              <SelectValue
                placeholder={
                  scopeType === "channel" ? "Pick a channel" : "Pick a brand"
                }
              />
            </SelectTrigger>
            <SelectContent>
              {scopeType === "channel"
                ? ALL_CHANNELS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {CHANNEL_DISPLAY_NAMES[c]}
                    </SelectItem>
                  ))
                : brands.map((b) => (
                    <SelectItem key={b.id} value={b.id}>
                      {b.name}
                    </SelectItem>
                  ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            disabled={saving || !scopeValue}
            onClick={() => {
              const label =
                scopeType === "channel"
                  ? `Channel: ${CHANNEL_DISPLAY_NAMES[scopeValue as Channel] || scopeValue}`
                  : `Brand: ${brandNames[scopeValue] || scopeValue.slice(0, 8)}`;
              setPending({
                enabled: false,
                scope:
                  scopeType === "channel"
                    ? { channel: scopeValue }
                    : { brand_id: scopeValue },
                label,
              });
            }}
          >
            <ShieldAlert className="h-3.5 w-3.5 mr-1" />
            Pause
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        title={
          pending?.enabled ? "Resume publishing?" : "Pause publishing?"
        }
        description={
          pending?.enabled
            ? `Publishing will resume for ${pending.label}. Items already due will publish on the next scheduler tick.`
            : `Publishing will be blocked for ${pending?.label ?? ""}. Due items stay queued untouched and publish once resumed. This is audit-logged.`
        }
        confirmLabel={pending?.enabled ? "Resume" : "Pause"}
        variant={pending?.enabled ? "default" : "destructive"}
        onConfirm={async () => {
          if (pending) {
            await applyChange(pending);
            setPending(null);
            setScopeValue("");
          }
        }}
      />
    </div>
  );
}
