"use client";

import React from "react";
import {
  CheckCircle2, AlertTriangle, Settings2, Save,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Channel } from "@/types";

interface ChannelConfig {
  enabled: boolean;
  configured: boolean;
  [key: string]: unknown;
}

export interface ChannelsTabProps {
  channelConfigs: Record<string, ChannelConfig>;
  expandedChannel: string | null;
  savingChannels: boolean;
  allChannels: Channel[];
  channelIconStyled: Record<string, { icon: React.ReactNode; color: string }>;
  channelDisplayNames: Record<Channel, string>;
  channelConfigFields: Record<Channel, { key: string; label: string; placeholder: string }[]>;
  onToggleChannelEnabled: (ch: string, enabled: boolean) => void;
  onUpdateChannelField: (ch: string, key: string, value: string) => void;
  onSetExpandedChannel: (ch: string | null) => void;
  onSaveChannels: () => Promise<void>;
}

export function ChannelsTab({
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
                        <div key={field.key} className="space-y-1">
                          <Label className="text-xs">{field.label}</Label>
                          <Input
                            className="h-8 text-sm"
                            placeholder={field.placeholder}
                            value={(cfg as Record<string, unknown>)[field.key] as string || ""}
                            onChange={(e) => onUpdateChannelField(ch, field.key, e.target.value)}
                          />
                        </div>
                      ))}
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
