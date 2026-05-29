"use client";

import React, { useEffect, useState } from "react";
import { Loader2, Save, Wand2 } from "lucide-react";
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

/** Safely coerce hashtags to a string[] regardless of backend format. */
function safeHashtags(raw: unknown): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(String);
  if (typeof raw === "string") {
    try { const parsed = JSON.parse(raw); if (Array.isArray(parsed)) return parsed.map(String); } catch { /* ignore */ }
    return raw.split(",").map(s => s.trim()).filter(Boolean);
  }
  return [];
}

interface ContentEditorProps {
  content: Content;
  onSave: (data: Partial<Content>) => Promise<void>;
  onRegenerateCaption?: () => Promise<void>;
  regeneratingCaption?: boolean;
}

export function ContentEditor({
  content,
  onSave,
  onRegenerateCaption,
  regeneratingCaption = false,
}: ContentEditorProps) {
  const [caption, setCaption] = useState(content.caption || content.body_text || "");
  const [hashtags, setHashtags] = useState(safeHashtags(content.hashtags).join(", "));
  const [cta, setCta] = useState(content.cta || content.cta_text || "");
  const [title, setTitle] = useState(content.title || content.headline || "");
  const [saving, setSaving] = useState(false);

  // Reflect parent-driven updates (e.g. after Regenerate Caption replaces
  // content.caption) back into the local editor state.
  useEffect(() => {
    setCaption(content.caption || content.body_text || "");
  }, [content.caption, content.body_text]);

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

  // Backend may return platform_adaptations or platform_metadata
  const adaptationsData = content.platform_adaptations || content.platform_metadata || (
    content.generation_metadata?.platform_adaptations as Record<string, Record<string, unknown>> | undefined
  );
  const platforms = adaptationsData && typeof adaptationsData === "object"
    ? Object.keys(adaptationsData)
    : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Content Editor</CardTitle>
          <div className="flex items-center gap-2">
            {content.status && <Badge className={statusColor(content.status)}>{content.status}</Badge>}
            {content.platform && (
              <Badge variant="outline" className="capitalize">
                {content.platform}
              </Badge>
            )}
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
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="caption">Caption</Label>
                {onRegenerateCaption && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 gap-1.5 text-xs"
                    disabled={regeneratingCaption}
                    onClick={() => onRegenerateCaption()}
                    title="Regenerate this caption with AI, using the brand voice and channel rules"
                  >
                    {regeneratingCaption ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Wand2 className="h-3.5 w-3.5" />
                    )}
                    {regeneratingCaption ? "Regenerating…" : "Regenerate"}
                  </Button>
                )}
              </div>
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
            const adaptation = (adaptationsData as Record<string, Record<string, unknown>>)?.[p] || {};
            const platCaption = String(adaptation?.caption || "");
            const platHashtags = safeHashtags(adaptation?.hashtags);
            return (
              <TabsContent key={p} value={p} className="space-y-4 mt-4">
                <div className="space-y-2">
                  <Label>Platform Caption</Label>
                  <Textarea value={platCaption} rows={4} readOnly className="opacity-75" />
                </div>
                <div className="space-y-2">
                  <Label>Platform Hashtags</Label>
                  <p className="text-sm text-primary">
                    {platHashtags.length > 0 ? platHashtags.map((h) => `#${h}`).join(" ") : "Same as main"}
                  </p>
                </div>
              </TabsContent>
            );
          })}
        </Tabs>

        {(content.media_urls || []).length > 0 && (
          <div className="space-y-2">
            <Label>Media Assets</Label>
            <div className="grid grid-cols-2 gap-4">
              {(content.media_urls || []).map((url, i) => (
                <AssetPreview key={i} url={url} alt={`Asset ${i + 1}`} />
              ))}
            </div>
          </div>
        )}

        {(content.ai_model_used || content.ai_model || content.ai_generated) && (
          <div className="rounded-md border p-3 bg-muted/50">
            <p className="text-xs text-muted-foreground">
              {content.ai_generated ? "AI Generated" : ""}
              {(content.ai_model_used || content.ai_model) && ` by ${content.ai_model_used || content.ai_model}`}
              {(content.prompt_version_id || content.ai_prompt_version) && ` (prompt: ${content.prompt_version_id || content.ai_prompt_version})`}
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
