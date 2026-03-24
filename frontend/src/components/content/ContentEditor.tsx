"use client";

import React, { useState } from "react";
import { Save } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { statusColor } from "@/lib/utils";
import { AssetPreview } from "./AssetPreview";
import type { Content } from "@/types";

interface ContentEditorProps {
  content: Content;
  onSave: (data: Partial<Content>) => Promise<void>;
}

export function ContentEditor({ content, onSave }: ContentEditorProps) {
  const [caption, setCaption] = useState(content.caption);
  const [hashtags, setHashtags] = useState(content.hashtags.join(", "));
  const [cta, setCta] = useState(content.cta || "");
  const [title, setTitle] = useState(content.title);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({
        title,
        caption,
        hashtags: hashtags
          .split(",")
          .map((h) => h.trim())
          .filter(Boolean),
        cta: cta || undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  const platforms = content.platform_adaptations
    ? Object.keys(content.platform_adaptations)
    : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Content Editor</CardTitle>
          <div className="flex items-center gap-2">
            <Badge className={statusColor(content.status)}>{content.status}</Badge>
            <Badge variant="outline" className="capitalize">
              {content.platform}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="title">Title</Label>
          <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>

        <Tabs defaultValue="main">
          <TabsList>
            <TabsTrigger value="main">Main</TabsTrigger>
            {platforms.map((p) => (
              <TabsTrigger key={p} value={p} className="capitalize">
                {p}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="main" className="space-y-4 mt-4">
            <div className="space-y-2">
              <Label htmlFor="caption">Caption</Label>
              <Textarea
                id="caption"
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                rows={6}
              />
              <p className="text-xs text-muted-foreground text-right">
                {caption.length} characters
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="hashtags">Hashtags</Label>
              <Input
                id="hashtags"
                value={hashtags}
                onChange={(e) => setHashtags(e.target.value)}
                placeholder="tag1, tag2, tag3"
              />
              <p className="text-xs text-muted-foreground">Comma-separated</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cta">Call to Action</Label>
              <Input
                id="cta"
                value={cta}
                onChange={(e) => setCta(e.target.value)}
                placeholder="e.g., Shop now, Learn more"
              />
            </div>
          </TabsContent>

          {platforms.map((p) => {
            const adaptation = content.platform_adaptations?.[p];
            return (
              <TabsContent key={p} value={p} className="space-y-4 mt-4">
                <div className="space-y-2">
                  <Label>Platform Caption</Label>
                  <Textarea value={adaptation?.caption || ""} rows={4} readOnly className="opacity-75" />
                </div>
                <div className="space-y-2">
                  <Label>Platform Hashtags</Label>
                  <p className="text-sm text-primary">
                    {adaptation?.hashtags?.map((h) => `#${h}`).join(" ") || "Same as main"}
                  </p>
                </div>
              </TabsContent>
            );
          })}
        </Tabs>

        {content.media_urls.length > 0 && (
          <div className="space-y-2">
            <Label>Media Assets</Label>
            <div className="grid grid-cols-2 gap-4">
              {content.media_urls.map((url, i) => (
                <AssetPreview key={i} url={url} alt={`Asset ${i + 1}`} />
              ))}
            </div>
          </div>
        )}

        {content.ai_model_used && (
          <div className="rounded-md border p-3 bg-muted/50">
            <p className="text-xs text-muted-foreground">
              Generated by: {content.ai_model_used}
              {content.prompt_version_id && ` (prompt: ${content.prompt_version_id})`}
            </p>
          </div>
        )}

        <div className="flex justify-end">
          <Button onClick={handleSave} disabled={saving}>
            <Save className="mr-2 h-4 w-4" />
            {saving ? "Saving..." : "Save Changes"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
