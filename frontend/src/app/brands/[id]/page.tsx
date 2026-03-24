"use client";

import React, { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Save, Trash2, CheckCircle2, AlertTriangle, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BrandForm } from "@/components/brand/BrandForm";
import { CompetitorTracker } from "@/components/brand/CompetitorTracker";
import { api } from "@/lib/api";
import { statusColor, formatDate } from "@/lib/utils";
import type { Brand, Content, EngagementMetrics, Channel } from "@/types";

const ALL_CHANNELS: Channel[] = [
  "instagram", "facebook", "linkedin", "youtube",
  "tiktok", "x", "website_blog", "teams",
];

const CHANNEL_DISPLAY_NAMES: Record<Channel, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  youtube: "YouTube",
  tiktok: "TikTok",
  x: "X (Twitter)",
  website_blog: "Website / Blog",
  teams: "Teams",
};

const CHANNEL_CONFIG_FIELDS: Record<Channel, { key: string; label: string; placeholder: string }[]> = {
  instagram: [
    { key: "handle", label: "Handle", placeholder: "@yourbrand" },
    { key: "access_token", label: "Access Token", placeholder: "Meta access token" },
  ],
  facebook: [
    { key: "page_id", label: "Page ID", placeholder: "Facebook Page ID" },
    { key: "access_token", label: "Access Token", placeholder: "Meta access token" },
  ],
  linkedin: [
    { key: "org_id", label: "Organization ID", placeholder: "LinkedIn Org ID" },
    { key: "access_token", label: "Access Token", placeholder: "LinkedIn access token" },
  ],
  youtube: [
    { key: "channel_id", label: "Channel ID", placeholder: "YouTube Channel ID" },
    { key: "api_key", label: "API Key", placeholder: "YouTube API key" },
  ],
  tiktok: [
    { key: "handle", label: "Handle", placeholder: "@yourbrand" },
    { key: "access_token", label: "Access Token", placeholder: "TikTok access token" },
  ],
  x: [
    { key: "handle", label: "Handle", placeholder: "@yourbrand" },
    { key: "api_key", label: "API Key", placeholder: "X API key" },
  ],
  website_blog: [
    { key: "url", label: "Blog URL (optional)", placeholder: "https://blog.example.com" },
  ],
  teams: [
    { key: "webhook_url", label: "Teams Webhook URL", placeholder: "https://outlook.office.com/webhook/..." },
  ],
};

interface ChannelConfig {
  enabled: boolean;
  configured: boolean;
  [key: string]: unknown;
}

export default function BrandDetailPage() {
  const params = useParams();
  const router = useRouter();
  const brandId = params.id as string;

  const [brand, setBrand] = useState<Brand | null>(null);
  const [content, setContent] = useState<Content[]>([]);
  const [metrics, setMetrics] = useState<EngagementMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [channelConfigs, setChannelConfigs] = useState<Record<string, ChannelConfig>>({});
  const [expandedChannel, setExpandedChannel] = useState<string | null>(null);
  const [savingChannels, setSavingChannels] = useState(false);

  useEffect(() => {
    async function fetchData() {
      try {
        const [brandData, contentData, metricsData] = await Promise.allSettled([
          api.get<Brand>(`/api/v1/brands/${brandId}`),
          api.get<Content[]>(`/api/v1/content`, { brand_id: brandId, limit: 20 }),
          api.get<EngagementMetrics>(`/api/v1/analytics/brands/${brandId}/metrics`),
        ]);

        if (brandData.status === "fulfilled") {
          setBrand(brandData.value);
          // Initialize channel configs from brand_guidelines
          const guidelines = brandData.value.brand_guidelines || {};
          const channels = (guidelines as Record<string, unknown>).channels as Record<string, ChannelConfig> | undefined;
          if (channels) {
            setChannelConfigs(channels);
          }
        }
        if (contentData.status === "fulfilled") setContent(contentData.value);
        if (metricsData.status === "fulfilled") setMetrics(metricsData.value);
      } catch {
        // Handle error
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [brandId]);

  const handleSave = async (data: Partial<Brand>) => {
    setSaving(true);
    try {
      const updated = await api.put<Brand>(`/api/v1/brands/${brandId}`, data);
      setBrand(updated);
    } catch {
      // Handle error
    } finally {
      setSaving(false);
    }
  };

  const toggleChannelEnabled = (ch: string, enabled: boolean) => {
    setChannelConfigs((prev) => ({
      ...prev,
      [ch]: { ...prev[ch], enabled, configured: prev[ch]?.configured ?? false },
    }));
  };

  const updateChannelField = (ch: string, key: string, value: string) => {
    setChannelConfigs((prev) => ({
      ...prev,
      [ch]: { ...prev[ch], [key]: value },
    }));
  };

  const handleSaveChannels = async () => {
    setSavingChannels(true);
    try {
      await api.put(`/api/v1/brands/${brandId}/channels`, { channels: channelConfigs });
    } catch {
      // Handle error
    } finally {
      setSavingChannels(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm("Are you sure you want to delete this brand?")) return;
    try {
      await api.delete(`/api/v1/brands/${brandId}`);
      router.push("/brands");
    } catch {
      // Handle error
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-[600px] w-full" />
      </div>
    );
  }

  if (!brand) {
    return (
      <div className="text-center py-12">
        <p className="text-lg text-muted-foreground">Brand not found</p>
        <Button variant="outline" className="mt-4" onClick={() => router.push("/brands")}>
          Back to Brands
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push("/brands")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold">{brand.name}</h1>
              <Badge className={statusColor(brand.status)}>{brand.status}</Badge>
            </div>
            <p className="text-muted-foreground">{brand.industry}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="destructive" size="sm" onClick={handleDelete}>
            <Trash2 className="mr-2 h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="channels">Channels</TabsTrigger>
          <TabsTrigger value="edit">Edit Brand</TabsTrigger>
          <TabsTrigger value="competitors">Competitors</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6 mt-6">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div>
                  <p className="text-sm text-muted-foreground">Description</p>
                  <p className="text-sm">{brand.description || "No description"}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Website</p>
                  <p className="text-sm">{brand.website_url || "Not set"}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Created</p>
                  <p className="text-sm">{formatDate(brand.created_at)}</p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Social Accounts</CardTitle>
              </CardHeader>
              <CardContent>
                {brand.social_accounts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No accounts connected</p>
                ) : (
                  <div className="space-y-2">
                    {brand.social_accounts.map((account, i) => (
                      <div key={i} className="flex items-center justify-between">
                        <div>
                          <p className="text-sm font-medium capitalize">{account.platform}</p>
                          <p className="text-xs text-muted-foreground">@{account.handle}</p>
                        </div>
                        <Badge variant={account.connected ? "default" : "outline"}>
                          {account.connected ? "Connected" : "Disconnected"}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Engagement</CardTitle>
              </CardHeader>
              <CardContent>
                {metrics ? (
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Impressions</span>
                      <span className="text-sm font-medium">{metrics.impressions.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Engagement Rate</span>
                      <span className="text-sm font-medium">{(metrics.engagement_rate * 100).toFixed(2)}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Likes</span>
                      <span className="text-sm font-medium">{metrics.likes.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Comments</span>
                      <span className="text-sm font-medium">{metrics.comments.toLocaleString()}</span>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No metrics data available</p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Recent Content</CardTitle>
              <CardDescription>Latest content for this brand</CardDescription>
            </CardHeader>
            <CardContent>
              {content.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">No content yet</p>
              ) : (
                <div className="space-y-2">
                  {content.slice(0, 5).map((item) => (
                    <div key={item.id} className="flex items-center justify-between rounded-md border p-3">
                      <div>
                        <p className="text-sm font-medium">{item.title}</p>
                        <p className="text-xs text-muted-foreground">{item.platform} - {formatDate(item.created_at)}</p>
                      </div>
                      <Badge className={statusColor(item.status)} variant="outline">
                        {item.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="channels" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Channel Configuration</CardTitle>
              <CardDescription>
                Enable and configure social channels for this brand
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {ALL_CHANNELS.map((ch) => {
                const cfg = channelConfigs[ch] || { enabled: false, configured: false };
                const isEnabled = cfg.enabled;
                const isConfigured = cfg.configured;
                const isExpanded = expandedChannel === ch;
                const fields = CHANNEL_CONFIG_FIELDS[ch];

                return (
                  <div key={ch} className="rounded-lg border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <Switch
                          checked={isEnabled}
                          onCheckedChange={(checked) => toggleChannelEnabled(ch, checked)}
                        />
                        <span className="font-medium">{CHANNEL_DISPLAY_NAMES[ch]}</span>
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
                        onClick={() => setExpandedChannel(isExpanded ? null : ch)}
                      >
                        <Settings2 className="h-4 w-4" />
                      </Button>
                    </div>

                    {isEnabled && !isConfigured && (
                      <div className="rounded-md bg-yellow-50 dark:bg-yellow-950 border border-yellow-200 dark:border-yellow-800 p-2">
                        <p className="text-xs text-yellow-700 dark:text-yellow-300">
                          Setup Required — this channel is enabled but not yet configured.
                        </p>
                      </div>
                    )}

                    {isExpanded && (
                      <div className="space-y-3 pt-2 border-t">
                        {fields.map((field) => (
                          <div key={field.key} className="space-y-1">
                            <Label className="text-sm">{field.label}</Label>
                            <Input
                              placeholder={field.placeholder}
                              value={(cfg as Record<string, unknown>)[field.key] as string || ""}
                              onChange={(e) => updateChannelField(ch, field.key, e.target.value)}
                            />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              <div className="flex justify-end pt-4">
                <Button onClick={handleSaveChannels} disabled={savingChannels}>
                  <Save className="mr-2 h-4 w-4" />
                  {savingChannels ? "Saving..." : "Save Channel Config"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="edit" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Edit Brand</CardTitle>
              <CardDescription>Update brand details and configuration</CardDescription>
            </CardHeader>
            <CardContent>
              <BrandForm brand={brand} onSubmit={handleSave} loading={saving} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="competitors" className="mt-6">
          <CompetitorTracker brandId={brandId} competitors={brand.competitors} />
        </TabsContent>

        <TabsContent value="performance" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Performance Analytics</CardTitle>
              <CardDescription>Engagement and content performance data</CardDescription>
            </CardHeader>
            <CardContent>
              {metrics ? (
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold">{metrics.reach.toLocaleString()}</p>
                    <p className="text-sm text-muted-foreground">Reach</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold">{metrics.impressions.toLocaleString()}</p>
                    <p className="text-sm text-muted-foreground">Impressions</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold">{(metrics.engagement_rate * 100).toFixed(2)}%</p>
                    <p className="text-sm text-muted-foreground">Engagement Rate</p>
                  </div>
                  <div className="rounded-lg border p-4 text-center">
                    <p className="text-2xl font-bold">{metrics.shares.toLocaleString()}</p>
                    <p className="text-sm text-muted-foreground">Shares</p>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-8">
                  No performance data available yet
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
