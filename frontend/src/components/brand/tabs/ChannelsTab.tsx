"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  CheckCircle2, AlertTriangle, Settings2, Save, Eye, EyeOff,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Channel } from "@/types";

const SENSITIVE_FIELD_KEYS = new Set([
  "access_token",
  "api_key",
  "refresh_token",
  "webhook_url",
  "client_secret",
]);

interface ChannelFieldInputProps {
  field: { key: string; label: string; placeholder: string };
  value: string | undefined;
  onChange: (value: string) => void;
}

function ChannelFieldInput({ field, value, onChange }: ChannelFieldInputProps) {
  const [revealed, setRevealed] = useState(false);
  const isSensitive = SENSITIVE_FIELD_KEYS.has(field.key);

  if (!isSensitive) {
    return (
      <div className="space-y-1">
        <Label className="text-xs">{field.label}</Label>
        <Input
          className="h-8 text-sm"
          placeholder={field.placeholder}
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <Label className="text-xs">{field.label}</Label>
      <div className="relative">
        <Input
          type={revealed ? "text" : "password"}
          className="h-8 text-sm pr-9"
          placeholder={field.placeholder}
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          onClick={() => setRevealed(!revealed)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          tabIndex={-1}
          aria-label={revealed ? "Hide token" : "Show token"}
        >
          {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}

interface TokenStatus {
  enabled: boolean;
  expires_at: string | null;
  status: string | null;
  days_left: number | null;
  source: string | null;
}

function LinkedinTokenStatus({ brandId }: { brandId: string }) {
  const [data, setData] = useState<TokenStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const check = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = await api.get<TokenStatus>(
        `/api/v1/brands/${brandId}/channels/linkedin/token-status`
      );
      setData(res);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [brandId]);

  useEffect(() => {
    check();
  }, [check]);

  const soon = data?.days_left != null && data.days_left <= 10;

  return (
    <div className="pt-2 mt-2 border-t text-xs space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">Token expiry (live)</span>
        <button
          type="button"
          onClick={check}
          disabled={loading}
          className="text-primary hover:underline disabled:opacity-50"
        >
          {loading ? "Checking…" : "Refresh"}
        </button>
      </div>
      {loading && <p className="text-muted-foreground">Checking with LinkedIn…</p>}
      {!loading && error && (
        <p className="text-red-500">Could not fetch token status.</p>
      )}
      {!loading && !error && data && (
        data.expires_at ? (
          <p className={soon ? "text-orange-600 dark:text-orange-400 font-medium" : "text-foreground"}>
            Expires {new Date(data.expires_at).toLocaleString()}
            {data.days_left != null && ` (${data.days_left}d left)`}
            {data.status && data.status !== "active" && ` — ${data.status}`}
            {data.source === "manual" && " · manual"}
          </p>
        ) : (
          <p className="text-muted-foreground">
            No expiry available — check Client ID / Secret &amp; access token, then Refresh.
          </p>
        )
      )}
    </div>
  );
}

interface ChannelConfig {
  enabled: boolean;
  configured: boolean;
  [key: string]: unknown;
}

export interface ChannelsTabProps {
  brandId: string;
  channelConfigs: Record<string, ChannelConfig>;
  expandedChannel: string | null;
  savingChannels: boolean;
  allChannels: Channel[];
  channelIconStyled: Record<string, { icon: React.ReactNode; color: string }>;
  channelDisplayNames: Record<Channel, string>;
  channelConfigFields: Record<Channel, { key: string; label: string; placeholder: string; optional?: boolean }[]>;
  onToggleChannelEnabled: (ch: string, enabled: boolean) => void;
  onUpdateChannelField: (ch: string, key: string, value: string) => void;
  onSetExpandedChannel: (ch: string | null) => void;
  onSaveChannels: () => Promise<void>;
}

export function ChannelsTab({
  brandId,
  channelConfigs,
  expandedChannel,
  savingChannels,
  allChannels,
  channelIconStyled,
  channelDisplayNames,
  channelConfigFields,
  onToggleChannelEnabled,
  onUpdateChannelField,
  onSetExpandedChannel,
  onSaveChannels,
}: ChannelsTabProps) {
  return (
    <div className="mt-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Channel Configuration</CardTitle>
          <CardDescription>
            Enable and configure social channels for this brand
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {allChannels.map((ch) => {
              const cfg = channelConfigs[ch] || { enabled: false, configured: false };
              const isEnabled = cfg.enabled;
              const isConfigured = cfg.configured;
              const isExpanded = expandedChannel === ch;
              const fields = channelConfigFields[ch];

              return (
                <div key={ch} className="rounded-lg border p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={isEnabled}
                      onCheckedChange={(checked) => onToggleChannelEnabled(ch, checked)}
                    />
                    <div className="flex-1 flex items-center justify-center gap-2">
                      <span className={`flex items-center justify-center h-6 w-6 rounded-sm ${channelIconStyled[ch]?.color || "bg-muted text-muted-foreground"}`}>
                        {channelIconStyled[ch]?.icon}
                      </span>
                      <span className="text-sm font-medium">{channelDisplayNames[ch]}</span>
                      {isEnabled && isConfigured && (
                        <CheckCircle2 className="h-4 w-4 text-green-500" />
                      )}
                      {isEnabled && !isConfigured && (
                        <AlertTriangle className="h-4 w-4 text-yellow-500" />
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0"
                      onClick={() => onSetExpandedChannel(isExpanded ? null : ch)}
                    >
                      <Settings2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>

                  {isEnabled && !isConfigured && (
                    <p className="text-[10px] text-yellow-600 dark:text-yellow-400">
                      Setup required
                    </p>
                  )}

                  {isExpanded && (
                    <div className="space-y-2 pt-2 border-t">
                      {fields.map((field) => (
                        <ChannelFieldInput
                          key={field.key}
                          field={field}
                          value={(cfg as Record<string, unknown>)[field.key] as string}
                          onChange={(value) => onUpdateChannelField(ch, field.key, value)}
                        />
                      ))}
                      {ch === "linkedin" && isEnabled && (
                        <LinkedinTokenStatus brandId={brandId} />
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="flex justify-end pt-4">
            <Button onClick={onSaveChannels} disabled={savingChannels}>
              <Save className="mr-2 h-4 w-4" />
              {savingChannels ? "Saving..." : "Save Channel Config"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
