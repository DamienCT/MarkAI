"use client";

import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Save, Wand2, Loader2, RefreshCw, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { ColorPalette, type ColorPaletteValue } from "@/components/brand/ColorPalette";
import { CHANNEL_DISPLAY_NAMES } from "@/lib/constants";
import type { Brand } from "@/types";

type ChannelCaptionSettings = {
  max_words?: number;
  hook_format?: string;
  tone_override?: string;
  emoji_override?: string;
  hashtags_count?: [number, number];
  must_name_product?: boolean;
  structure_template?: string;
  caption_brief?: string;
};

type ChannelCaptionsMap = Record<string, ChannelCaptionSettings>;

interface BrandFormProps {
  brand?: Brand;
  onSubmit: (data: Partial<Brand>) => Promise<void>;
  loading?: boolean;
}

interface AIGenerateResponse {
  fields: Record<string, string>;
}

interface AIRewriteResponse {
  value: string;
}

function AiWandButton({
  onClick,
  generating,
  title,
}: {
  onClick: () => void;
  generating: boolean;
  title?: string;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="h-6 w-6 p-0 text-muted-foreground hover:text-primary"
      onClick={onClick}
      disabled={generating}
      title={title || "Generate with AI"}
    >
      {generating ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Wand2 className="h-3.5 w-3.5" />
      )}
    </Button>
  );
}

function ChannelCaptionEditor({
  channel,
  label,
  value,
  onChange,
}: {
  channel: string;
  label: string;
  value: ChannelCaptionSettings;
  onChange: (next: ChannelCaptionSettings) => void;
}) {
  const set = <K extends keyof ChannelCaptionSettings>(
    key: K,
    v: ChannelCaptionSettings[K] | undefined
  ) => {
    const next: ChannelCaptionSettings = { ...value };
    if (v === undefined || v === "" || (typeof v === "number" && Number.isNaN(v))) {
      delete next[key];
    } else {
      next[key] = v;
    }
    onChange(next);
  };

  const hMin = value.hashtags_count?.[0];
  const hMax = value.hashtags_count?.[1];
  const setHashtags = (idx: 0 | 1, n: number | undefined) => {
    const min = idx === 0 ? n : hMin;
    const max = idx === 1 ? n : hMax;
    if (min === undefined && max === undefined) {
      set("hashtags_count", undefined);
    } else {
      set("hashtags_count", [min ?? 0, max ?? 0]);
    }
  };

  return (
    <details className="rounded-md border p-3 group">
      <summary className="cursor-pointer text-sm font-medium select-none flex items-center justify-between">
        <span>{label}</span>
        <span className="text-xs text-muted-foreground">
          {Object.keys(value).length > 0 ? "configured" : "inherit global"}
        </span>
      </summary>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor={`${channel}-max-words`} className="text-xs">Max words</Label>
          <Input
            id={`${channel}-max-words`}
            type="number"
            min={10}
            max={2000}
            value={value.max_words ?? ""}
            onChange={(e) =>
              set("max_words", e.target.value ? Number(e.target.value) : undefined)
            }
            placeholder="inherit"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${channel}-hook-format`} className="text-xs">Hook format</Label>
          <Input
            id={`${channel}-hook-format`}
            value={value.hook_format ?? ""}
            onChange={(e) => set("hook_format", e.target.value || undefined)}
            placeholder="e.g. 3-word punch"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${channel}-tone-override`} className="text-xs">Tone override</Label>
          <Input
            id={`${channel}-tone-override`}
            value={value.tone_override ?? ""}
            onChange={(e) => set("tone_override", e.target.value || undefined)}
            placeholder="e.g. warm, sensory, gourmand"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${channel}-emoji-override`} className="text-xs">Emoji override</Label>
          <Select
            value={value.emoji_override ?? "__inherit__"}
            onValueChange={(v) =>
              set("emoji_override", v === "__inherit__" ? undefined : v)
            }
          >
            <SelectTrigger id={`${channel}-emoji-override`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__inherit__">Inherit global</SelectItem>
              <SelectItem value="none">None</SelectItem>
              <SelectItem value="minimal">Minimal</SelectItem>
              <SelectItem value="moderate">Moderate</SelectItem>
              <SelectItem value="heavy">Heavy</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Hashtags min</Label>
          <Input
            type="number"
            min={0}
            max={30}
            value={hMin ?? ""}
            onChange={(e) =>
              setHashtags(0, e.target.value ? Number(e.target.value) : undefined)
            }
            placeholder="inherit"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Hashtags max</Label>
          <Input
            type="number"
            min={0}
            max={30}
            value={hMax ?? ""}
            onChange={(e) =>
              setHashtags(1, e.target.value ? Number(e.target.value) : undefined)
            }
            placeholder="inherit"
          />
        </div>
        <div className="space-y-1 md:col-span-2">
          <Label htmlFor={`${channel}-structure`} className="text-xs">Structure template</Label>
          <Input
            id={`${channel}-structure`}
            value={value.structure_template ?? ""}
            onChange={(e) => set("structure_template", e.target.value || undefined)}
            placeholder="e.g. hook | tension | sensory line | CTA"
          />
        </div>
        <div className="space-y-1 md:col-span-2">
          <Label htmlFor={`${channel}-brief`} className="text-xs">
            Caption brief override (full freedom)
          </Label>
          <Textarea
            id={`${channel}-brief`}
            rows={3}
            value={value.caption_brief ?? ""}
            onChange={(e) => set("caption_brief", e.target.value || undefined)}
            placeholder="Free-form: anything written here is injected verbatim for this channel only."
          />
        </div>
        <div className="flex items-center gap-2 md:col-span-2">
          <input
            id={`${channel}-must-name-product`}
            type="checkbox"
            className="h-4 w-4"
            checked={!!value.must_name_product}
            onChange={(e) =>
              set("must_name_product", e.target.checked || undefined)
            }
          />
          <Label htmlFor={`${channel}-must-name-product`} className="text-xs">
            Must mention the product name
          </Label>
        </div>
      </div>
    </details>
  );
}


function AiRewriteButton({
  onClick,
  rewriting,
  title,
}: {
  onClick: () => void;
  rewriting: boolean;
  title?: string;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="h-6 w-6 p-0 text-muted-foreground hover:text-blue-500"
      onClick={onClick}
      disabled={rewriting}
      title={title || "Rewrite with AI"}
    >
      {rewriting ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <RefreshCw className="h-3.5 w-3.5" />
      )}
    </Button>
  );
}

export function BrandForm({ brand, onSubmit, loading }: BrandFormProps) {
  const [name, setName] = useState(brand?.name || "");
  const [slug, setSlug] = useState(brand?.slug || "");
  const [description, setDescription] = useState(brand?.description || "");
  const [websiteUrl, setWebsiteUrl] = useState(brand?.website_url || "");
  const [toneOfVoice, setToneOfVoice] = useState(brand?.tone_of_voice || "");

  const guidelines = (brand?.brand_guidelines || {}) as Record<string, unknown>;
  const [additionalWebsites, setAdditionalWebsites] = useState<string[]>(
    ((guidelines.websites as string[]) || [])
  );
  const [voiceStyle, setVoiceStyle] = useState((guidelines.voice_style as string) || "");
  const [emojiUsage, setEmojiUsage] = useState((guidelines.emoji_usage as string) || "moderate");
  const [hashtagStrategy, setHashtagStrategy] = useState((guidelines.hashtag_strategy as string) || "");
  const [dos, setDos] = useState(((guidelines.dos as string[]) || []).join("\n"));
  const [donts, setDonts] = useState(((guidelines.donts as string[]) || []).join("\n"));

  // Per-channel caption overrides — layered read at agent side:
  // channel.caption.<field> > brand global > system defaults. Empty fields
  // mean "inherit". We seed from existing brand_guidelines.channels.<ch>.caption.
  const [channelCaptions, setChannelCaptions] = useState<ChannelCaptionsMap>(() => {
    const channelsCfg =
      (guidelines.channels as Record<string, Record<string, unknown>>) || {};
    const out: ChannelCaptionsMap = {};
    Object.keys(CHANNEL_DISPLAY_NAMES).forEach((ch) => {
      const cfg = channelsCfg[ch];
      const caption =
        cfg && typeof cfg === "object"
          ? ((cfg as Record<string, unknown>).caption as ChannelCaptionSettings | undefined)
          : undefined;
      out[ch] = caption || {};
    });
    return out;
  });

  const [targetAudience, setTargetAudience] = useState(
    typeof brand?.target_audience === "object" && brand?.target_audience
      ? (brand.target_audience as Record<string, string>).description || ""
      : ""
  );

  const DEFAULT_COLORS: ColorPaletteValue = { primary: "#1a1a2e", secondary: "#16213e", accent: "#e94560" };
  const existingPalette = brand?.color_palette as Partial<ColorPaletteValue> | undefined;
  const [colorPalette, setColorPalette] = useState<ColorPaletteValue>({
    primary: existingPalette?.primary || DEFAULT_COLORS.primary,
    secondary: existingPalette?.secondary || DEFAULT_COLORS.secondary,
    accent: existingPalette?.accent || DEFAULT_COLORS.accent,
  });

  const [bcCompany, setBcCompany] = useState<string | null>(brand?.bc_company ?? null);
  const [bcLocations, setBcLocations] = useState<string[]>(brand?.bc_locations ?? []);
  const [availableCompanies, setAvailableCompanies] = useState<string[]>([]);
  const [availableLocations, setAvailableLocations] = useState<string[]>([]);
  const [loadingCompanies, setLoadingCompanies] = useState(false);
  const [loadingLocations, setLoadingLocations] = useState(false);

  // AI generation state
  const [generatingField, setGeneratingField] = useState<string | null>(null);
  const [generatingAll, setGeneratingAll] = useState(false);
  const [rewritingField, setRewritingField] = useState<string | null>(null);

  const fetchCompanies = useCallback(async () => {
    setLoadingCompanies(true);
    try {
      const companies = await api.get<string[]>("/api/v1/brands/bc-companies");
      setAvailableCompanies(companies);
    } catch {
      toast.error("Failed to load BC companies");
    } finally {
      setLoadingCompanies(false);
    }
  }, []);

  const fetchLocations = useCallback(async (company: string) => {
    setLoadingLocations(true);
    try {
      const locations = await api.get<string[]>(
        `/api/v1/brands/bc-locations?company=${encodeURIComponent(company)}`
      );
      setAvailableLocations(locations);
    } catch {
      toast.error("Failed to load BC locations");
    } finally {
      setLoadingLocations(false);
    }
  }, []);

  useEffect(() => {
    fetchCompanies();
  }, [fetchCompanies]);

  useEffect(() => {
    if (bcCompany) fetchLocations(bcCompany);
    else setAvailableLocations([]);
  }, [bcCompany, fetchLocations]);

  const handleCompanyChange = (value: string) => {
    if (value === "__skip__") {
      setBcCompany(null);
      setBcLocations([]);
      setAvailableLocations([]);
      return;
    }
    setBcCompany(value);
    setBcLocations([]);
  };

  const toggleLocation = (location: string) => {
    setBcLocations((prev) =>
      prev.includes(location) ? prev.filter((l) => l !== location) : [...prev, location]
    );
  };

  const applyGeneratedFields = (fields: Record<string, string>) => {
    if (fields.description) setDescription(fields.description);
    if (fields.target_audience) setTargetAudience(fields.target_audience);
    if (fields.tone_of_voice) setToneOfVoice(fields.tone_of_voice);
    if (fields.voice_style) setVoiceStyle(fields.voice_style);
    if (fields.hashtag_strategy) setHashtagStrategy(fields.hashtag_strategy);
    if (fields.dos) setDos(fields.dos);
    if (fields.donts) setDonts(fields.donts);
  };

  const handleGenerateField = async (field: string) => {
    if (!brand?.id) {
      toast.error("Save the brand first before using AI generation");
      return;
    }
    setGeneratingField(field);
    try {
      const result = await api.post<AIGenerateResponse>("/api/v1/intelligence/generate-fields", {
        brand_id: brand.id,
        field,
      });
      applyGeneratedFields(result.fields);
      toast.success(`AI generated ${field.replace(/_/g, " ")}`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "AI generation failed";
      toast.error(detail);
    } finally {
      setGeneratingField(null);
    }
  };

  const handleGenerateAll = async () => {
    if (!brand?.id) {
      toast.error("Save the brand first before using AI generation");
      return;
    }
    setGeneratingAll(true);
    try {
      const result = await api.post<AIGenerateResponse>("/api/v1/intelligence/generate-fields", {
        brand_id: brand.id,
        field: null, // null = generate all empty fields
      });
      const count = Object.keys(result.fields).length;
      if (count === 0) {
        toast.info("All fields are already filled");
      } else {
        applyGeneratedFields(result.fields);
        toast.success(`AI populated ${count} field${count !== 1 ? "s" : ""}`);
      }
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "AI generation failed";
      toast.error(detail);
    } finally {
      setGeneratingAll(false);
    }
  };

  const getFieldValue = (field: string): string => {
    switch (field) {
      case "description": return description;
      case "target_audience": return targetAudience;
      case "tone_of_voice": return toneOfVoice;
      case "voice_style": return voiceStyle;
      case "hashtag_strategy": return hashtagStrategy;
      case "dos": return dos;
      case "donts": return donts;
      default: return "";
    }
  };

  const setFieldValue = (field: string, value: string) => {
    switch (field) {
      case "description": setDescription(value); break;
      case "target_audience": setTargetAudience(value); break;
      case "tone_of_voice": setToneOfVoice(value); break;
      case "voice_style": setVoiceStyle(value); break;
      case "hashtag_strategy": setHashtagStrategy(value); break;
      case "dos": setDos(value); break;
      case "donts": setDonts(value); break;
    }
  };

  const handleRewriteField = async (field: string) => {
    if (!brand?.id) {
      toast.error("Save the brand first");
      return;
    }
    const currentValue = getFieldValue(field);
    if (!currentValue.trim()) {
      toast.error("Field is empty — use the wand to generate first");
      return;
    }
    setRewritingField(field);
    try {
      const result = await api.post<AIRewriteResponse>("/api/v1/intelligence/rewrite-field", {
        brand_id: brand.id,
        field,
        current_value: currentValue,
      });
      setFieldValue(field, result.value);
      toast.success(`Rephrased ${field.replace(/_/g, " ")}`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Rewrite failed";
      toast.error(detail);
    } finally {
      setRewritingField(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      toast.error("Brand name is required");
      return;
    }

    // Validate URLs
    const urlsToValidate = [websiteUrl, ...additionalWebsites].filter(Boolean);
    for (const url of urlsToValidate) {
      try {
        const parsed = new URL(url);
        if (!["http:", "https:"].includes(parsed.protocol)) {
          toast.error(`Invalid URL protocol: ${url}`);
          return;
        }
      } catch {
        toast.error(`Invalid URL: ${url}`);
        return;
      }
    }

    const existingGuidelines = (brand?.brand_guidelines || {}) as Record<string, unknown>;
    const newGuidelines: Record<string, unknown> = {
      ...existingGuidelines,
      voice_style: voiceStyle || undefined,
      emoji_usage: emojiUsage || undefined,
      hashtag_strategy: hashtagStrategy || undefined,
      dos: dos ? dos.split("\n").filter(Boolean) : [],
      donts: donts ? donts.split("\n").filter(Boolean) : [],
    };

    // Merge per-channel caption overrides into brand_guidelines.channels.<ch>.caption.
    // Preserve any other per-channel config (enabled flag, handle, access_token, etc.)
    // already stored by the Channels tab.
    const existingChannels =
      (existingGuidelines.channels as Record<string, Record<string, unknown>>) || {};
    const mergedChannels: Record<string, Record<string, unknown>> = {
      ...existingChannels,
    };
    Object.entries(channelCaptions).forEach(([ch, caption]) => {
      const cleaned = Object.fromEntries(
        Object.entries(caption).filter(
          ([, v]) => v !== undefined && v !== "" && v !== null
        )
      );
      const prior = mergedChannels[ch] || {};
      if (Object.keys(cleaned).length > 0) {
        mergedChannels[ch] = { ...prior, caption: cleaned };
      } else if ("caption" in prior) {
        const updated: Record<string, unknown> = { ...prior };
        delete updated.caption;
        mergedChannels[ch] = updated;
      }
    });
    newGuidelines.channels = mergedChannels;

    // Store additional websites in brand_guidelines
    const filteredWebsites = additionalWebsites.filter((u) => u.trim());
    if (filteredWebsites.length > 0) {
      newGuidelines.websites = filteredWebsites;
    }

    await onSubmit({
      name,
      slug: slug || name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, ""),
      description: description || null,
      website_url: websiteUrl || null,
      tone_of_voice: toneOfVoice || null,
      target_audience: targetAudience ? { description: targetAudience } : {},
      brand_guidelines: newGuidelines,
      color_palette: colorPalette,
      is_bc_linked: !!bcCompany,
      bc_company: bcCompany || null,
      bc_locations: bcLocations,
    } as Partial<Brand>);
  };

  const isGenerating = generatingField !== null || generatingAll || rewritingField !== null;

  return (
    <form onSubmit={handleSubmit}>
      <Tabs defaultValue="details">
        <TabsList>
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="voice">Voice Profile</TabsTrigger>
          <TabsTrigger value="bc">Business Central</TabsTrigger>
        </TabsList>

        <TabsContent value="details" className="space-y-4 mt-4">
          {/* AI Fill All button */}
          {brand?.id && (
            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleGenerateAll}
                disabled={isGenerating}
              >
                {generatingAll ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Wand2 className="mr-2 h-3.5 w-3.5" />
                )}
                {generatingAll ? "Generating..." : "AI Fill Empty Fields"}
              </Button>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="name">Brand Name *</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="slug">Slug</Label>
              <Input id="slug" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="auto-generated-from-name" />
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <Label htmlFor="description">Description</Label>
              {brand?.id && (
                <>
                  <AiWandButton
                    onClick={() => handleGenerateField("description")}
                    generating={generatingField === "description"}
                    title="Generate from context"
                  />
                  <AiRewriteButton
                    onClick={() => handleRewriteField("description")}
                    rewriting={rewritingField === "description"}
                    title="Rephrase with AI"
                  />
                </>
              )}
            </div>
            <Textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
          </div>

          {/* Websites */}
          <div className="space-y-3">
            <Label>Brand Websites</Label>
            <div className="space-y-2">
              <div className="flex gap-2">
                <Input
                  value={websiteUrl}
                  onChange={(e) => setWebsiteUrl(e.target.value)}
                  placeholder="Primary website (e.g., https://healthspan.mu)"
                  type="url"
                />
                <Badge variant="secondary" className="shrink-0 self-center">Primary</Badge>
              </div>
              {additionalWebsites.map((url, i) => (
                <div key={i} className="flex gap-2">
                  <Input
                    value={url}
                    onChange={(e) => {
                      const updated = [...additionalWebsites];
                      updated[i] = e.target.value;
                      setAdditionalWebsites(updated);
                    }}
                    placeholder="Additional URL (e.g., https://shop.healthspan.mu)"
                    type="url"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={() => setAdditionalWebsites(additionalWebsites.filter((_, j) => j !== i))}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setAdditionalWebsites([...additionalWebsites, ""])}
              >
                + Add Website
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              All URLs are used for AI research, competitor analysis, and content generation — even if the channel is off.
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <Label htmlFor="audience">Target Audience</Label>
              {brand?.id && (
                <>
                  <AiWandButton onClick={() => handleGenerateField("target_audience")} generating={generatingField === "target_audience"} title="Generate from context" />
                  <AiRewriteButton onClick={() => handleRewriteField("target_audience")} rewriting={rewritingField === "target_audience"} title="Rephrase with AI" />
                </>
              )}
            </div>
            <Input
              id="audience"
              value={targetAudience}
              onChange={(e) => setTargetAudience(e.target.value)}
              placeholder="e.g., Women 25-45, fashion-conscious"
            />
          </div>

          <Separator />

          {/* Brand Colors */}
          <ColorPalette value={colorPalette} onChange={setColorPalette} />
        </TabsContent>

        <TabsContent value="voice" className="space-y-4 mt-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <div className="flex items-center gap-1">
                <Label htmlFor="tone">Tone of Voice</Label>
                {brand?.id && (
                  <>
                    <AiWandButton onClick={() => handleGenerateField("tone_of_voice")} generating={generatingField === "tone_of_voice"} title="Generate from context" />
                    <AiRewriteButton onClick={() => handleRewriteField("tone_of_voice")} rewriting={rewritingField === "tone_of_voice"} title="Rephrase with AI" />
                  </>
                )}
              </div>
              <Input
                id="tone"
                value={toneOfVoice}
                onChange={(e) => setToneOfVoice(e.target.value)}
                placeholder="friendly, professional, witty"
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-1">
                <Label htmlFor="style">Style</Label>
                {brand?.id && (
                  <>
                    <AiWandButton onClick={() => handleGenerateField("voice_style")} generating={generatingField === "voice_style"} title="Generate from context" />
                    <AiRewriteButton onClick={() => handleRewriteField("voice_style")} rewriting={rewritingField === "voice_style"} title="Rephrase with AI" />
                  </>
                )}
              </div>
              <Input
                id="style"
                value={voiceStyle}
                onChange={(e) => setVoiceStyle(e.target.value)}
                placeholder="e.g., conversational, formal"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="emoji">Emoji Usage</Label>
              <Select value={emojiUsage} onValueChange={setEmojiUsage}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="minimal">Minimal</SelectItem>
                  <SelectItem value="moderate">Moderate</SelectItem>
                  <SelectItem value="heavy">Heavy</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-1">
                <Label htmlFor="hashtag">Hashtag Strategy</Label>
                {brand?.id && (
                  <>
                    <AiWandButton onClick={() => handleGenerateField("hashtag_strategy")} generating={generatingField === "hashtag_strategy"} title="Generate from context" />
                    <AiRewriteButton onClick={() => handleRewriteField("hashtag_strategy")} rewriting={rewritingField === "hashtag_strategy"} title="Rephrase with AI" />
                  </>
                )}
              </div>
              <Input
                id="hashtag"
                value={hashtagStrategy}
                onChange={(e) => setHashtagStrategy(e.target.value)}
                placeholder="e.g., mix of branded and trending"
              />
            </div>
          </div>

          <Separator />

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <div className="flex items-center gap-1">
                <Label htmlFor="dos">Do&apos;s (one per line)</Label>
                {brand?.id && (
                  <>
                    <AiWandButton onClick={() => handleGenerateField("dos")} generating={generatingField === "dos"} title="Generate from context" />
                    <AiRewriteButton onClick={() => handleRewriteField("dos")} rewriting={rewritingField === "dos"} title="Rephrase with AI" />
                  </>
                )}
              </div>
              <Textarea
                id="dos"
                value={dos}
                onChange={(e) => setDos(e.target.value)}
                rows={5}
                placeholder={"Use inclusive language\nReference seasonal themes\nInclude CTAs"}
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-1">
                <Label htmlFor="donts">Don&apos;ts (one per line)</Label>
                {brand?.id && (
                  <>
                    <AiWandButton onClick={() => handleGenerateField("donts")} generating={generatingField === "donts"} title="Generate from context" />
                    <AiRewriteButton onClick={() => handleRewriteField("donts")} rewriting={rewritingField === "donts"} title="Rephrase with AI" />
                  </>
                )}
              </div>
              <Textarea
                id="donts"
                value={donts}
                onChange={(e) => setDonts(e.target.value)}
                rows={5}
                placeholder={"No controversial topics\nNo competitor mentions\nAvoid jargon"}
              />
            </div>
          </div>

          <Separator />

          <div className="space-y-3">
            <div>
              <Label className="text-sm">Per-channel overrides</Label>
              <p className="text-xs text-muted-foreground mt-1">
                Optional. Each channel can override the global voice settings
                above. Empty fields inherit the global value. Length defaults
                are tuned per platform (Instagram 60, Facebook 90, LinkedIn 120,
                TikTok 30, X 35) — override only when you want a different limit.
              </p>
            </div>
            <div className="space-y-2">
              {Object.entries(CHANNEL_DISPLAY_NAMES).map(([ch, label]) => (
                <ChannelCaptionEditor
                  key={ch}
                  channel={ch}
                  label={label}
                  value={channelCaptions[ch] || {}}
                  onChange={(next) =>
                    setChannelCaptions((prev) => ({ ...prev, [ch]: next }))
                  }
                />
              ))}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="bc" className="space-y-4 mt-4">
          <div className="space-y-2">
            <Label>Business Central Integration</Label>
            <p className="text-sm text-muted-foreground">
              Link this brand to a Business Central company to sync products and stock levels.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="bc-company">Select BC Company</Label>
            <Select
              value={bcCompany ?? "__skip__"}
              onValueChange={handleCompanyChange}
            >
              <SelectTrigger className="flex-1">
                <SelectValue placeholder={loadingCompanies ? "Loading companies..." : "Select a company"} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__skip__">Link Later (skip)</SelectItem>
                {availableCompanies.map((company) => (
                  <SelectItem key={company} value={company}>{company}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {bcCompany && (
            <div className="space-y-2">
              <Label>Select Stock Locations</Label>
              {loadingLocations ? (
                <p className="text-sm text-muted-foreground">Loading locations...</p>
              ) : availableLocations.length === 0 ? (
                <p className="text-sm text-muted-foreground">No locations found for this company.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {availableLocations.map((location) => (
                    <Badge
                      key={location}
                      variant={bcLocations.includes(location) ? "default" : "outline"}
                      className="cursor-pointer select-none"
                      onClick={() => toggleLocation(location)}
                    >
                      {location}
                    </Badge>
                  ))}
                </div>
              )}
              {bcLocations.length > 0 && (
                <p className="text-sm text-muted-foreground mt-2">Selected: {bcLocations.join(", ")}</p>
              )}
            </div>
          )}

          {bcCompany && (
            <div className="rounded-md border p-4 mt-4 bg-muted/50">
              <h4 className="text-sm font-medium mb-2">BC Integration Summary</h4>
              <dl className="text-sm space-y-1">
                <div className="flex gap-2">
                  <dt className="font-medium">Company:</dt>
                  <dd>{bcCompany}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="font-medium">Locations:</dt>
                  <dd>{bcLocations.length > 0 ? bcLocations.join(", ") : "None selected"}</dd>
                </div>
              </dl>
            </div>
          )}
        </TabsContent>
      </Tabs>

      <div className="flex justify-end mt-6">
        <Button type="submit" disabled={loading || !name.trim()}>
          <Save className="mr-2 h-4 w-4" />
          {loading ? "Saving..." : brand ? "Update Brand" : "Create Brand"}
        </Button>
      </div>
    </form>
  );
}
