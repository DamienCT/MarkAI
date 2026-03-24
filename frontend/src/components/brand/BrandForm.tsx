"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Save } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { Brand } from "@/types";

interface BrandFormProps {
  brand?: Brand;
  onSubmit: (data: Partial<Brand>) => Promise<void>;
  loading?: boolean;
}

export function BrandForm({ brand, onSubmit, loading }: BrandFormProps) {
  const [name, setName] = useState(brand?.name || "");
  const [slug, setSlug] = useState(brand?.slug || "");
  const [description, setDescription] = useState(brand?.description || "");
  const [industry, setIndustry] = useState(brand?.industry || "");
  const [websiteUrl, setWebsiteUrl] = useState(brand?.website_url || "");
  const [status, setStatus] = useState(brand?.status || "onboarding");
  const [targetAudience, setTargetAudience] = useState(brand?.target_audience || "");
  const [brandGuidelines, setBrandGuidelines] = useState(brand?.brand_guidelines || "");
  const [voiceTone, setVoiceTone] = useState(brand?.voice_profile?.tone?.join(", ") || "");
  const [voiceStyle, setVoiceStyle] = useState(brand?.voice_profile?.style || "");
  const [emojiUsage, setEmojiUsage] = useState(brand?.voice_profile?.emoji_usage || "moderate");
  const [hashtagStrategy, setHashtagStrategy] = useState(brand?.voice_profile?.hashtag_strategy || "");
  const [dos, setDos] = useState(brand?.voice_profile?.dos?.join("\n") || "");
  const [donts, setDonts] = useState(brand?.voice_profile?.donts?.join("\n") || "");

  // BC Integration state
  const [bcCompany, setBcCompany] = useState<string | null>(brand?.bc_company ?? null);
  const [bcLocations, setBcLocations] = useState<string[]>(brand?.bc_locations ?? []);
  const [availableCompanies, setAvailableCompanies] = useState<string[]>([]);
  const [availableLocations, setAvailableLocations] = useState<string[]>([]);
  const [loadingCompanies, setLoadingCompanies] = useState(false);
  const [loadingLocations, setLoadingLocations] = useState(false);

  const fetchCompanies = useCallback(async () => {
    setLoadingCompanies(true);
    try {
      const companies = await api.get<string[]>("/api/v1/brands/bc-companies");
      setAvailableCompanies(companies);
    } catch {
      // Handle error silently
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
      // Handle error silently
    } finally {
      setLoadingLocations(false);
    }
  }, []);

  useEffect(() => {
    if (bcCompany) {
      fetchLocations(bcCompany);
    } else {
      setAvailableLocations([]);
    }
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
      prev.includes(location)
        ? prev.filter((l) => l !== location)
        : [...prev, location]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSubmit({
      name,
      slug: slug || name.toLowerCase().replace(/\s+/g, "-"),
      description,
      industry,
      website_url: websiteUrl || undefined,
      status: status as Brand["status"],
      target_audience: targetAudience || undefined,
      brand_guidelines: brandGuidelines || undefined,
      bc_company: bcCompany,
      bc_locations: bcLocations,
      voice_profile: {
        tone: voiceTone.split(",").map((t) => t.trim()).filter(Boolean),
        style: voiceStyle,
        vocabulary_level: "professional",
        emoji_usage: emojiUsage,
        hashtag_strategy: hashtagStrategy,
        dos: dos.split("\n").filter(Boolean),
        donts: donts.split("\n").filter(Boolean),
      },
    });
  };

  return (
    <form onSubmit={handleSubmit}>
      <Tabs defaultValue="details">
        <TabsList>
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="voice">Voice Profile</TabsTrigger>
          <TabsTrigger value="bc">Business Central</TabsTrigger>
          <TabsTrigger value="social">Social Accounts</TabsTrigger>
        </TabsList>

        <TabsContent value="details" className="space-y-4 mt-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="name">Brand Name *</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="slug">Slug</Label>
              <Input
                id="slug"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="auto-generated-from-name"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="industry">Industry</Label>
              <Input
                id="industry"
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                placeholder="e.g., Fashion, Technology"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="website">Website URL</Label>
              <Input
                id="website"
                type="url"
                value={websiteUrl}
                onChange={(e) => setWebsiteUrl(e.target.value)}
                placeholder="https://"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="status">Status</Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="onboarding">Onboarding</SelectItem>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="inactive">Inactive</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="audience">Target Audience</Label>
              <Input
                id="audience"
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value)}
                placeholder="e.g., Women 25-45, fashion-conscious"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="guidelines">Brand Guidelines</Label>
            <Textarea
              id="guidelines"
              value={brandGuidelines}
              onChange={(e) => setBrandGuidelines(e.target.value)}
              rows={4}
              placeholder="Key brand guidelines and rules..."
            />
          </div>
        </TabsContent>

        <TabsContent value="voice" className="space-y-4 mt-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="tone">Tone (comma-separated)</Label>
              <Input
                id="tone"
                value={voiceTone}
                onChange={(e) => setVoiceTone(e.target.value)}
                placeholder="friendly, professional, witty"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="style">Style</Label>
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
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="minimal">Minimal</SelectItem>
                  <SelectItem value="moderate">Moderate</SelectItem>
                  <SelectItem value="heavy">Heavy</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="hashtag">Hashtag Strategy</Label>
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
              <Label htmlFor="dos">Do&apos;s (one per line)</Label>
              <Textarea
                id="dos"
                value={dos}
                onChange={(e) => setDos(e.target.value)}
                rows={5}
                placeholder="Use inclusive language&#10;Reference seasonal themes&#10;Include CTAs"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="donts">Don&apos;ts (one per line)</Label>
              <Textarea
                id="donts"
                value={donts}
                onChange={(e) => setDonts(e.target.value)}
                rows={5}
                placeholder="No controversial topics&#10;No competitor mentions&#10;Avoid jargon"
              />
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
            <div className="flex gap-2">
              <Select
                value={bcCompany ?? ""}
                onValueChange={handleCompanyChange}
                onOpenChange={(open) => {
                  if (open && availableCompanies.length === 0) {
                    fetchCompanies();
                  }
                }}
              >
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder={loadingCompanies ? "Loading companies..." : "Select a company"} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__skip__">Link Later (skip)</SelectItem>
                  {availableCompanies.map((company) => (
                    <SelectItem key={company} value={company}>
                      {company}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
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
                <p className="text-sm text-muted-foreground mt-2">
                  Selected: {bcLocations.join(", ")}
                </p>
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

        <TabsContent value="social" className="mt-4">
          <div className="text-center py-8">
            <p className="text-muted-foreground">
              Social account connections are managed through the platform integrations.
            </p>
            {brand?.social_accounts && brand.social_accounts.length > 0 && (
              <div className="mt-4 space-y-2 max-w-md mx-auto">
                {brand.social_accounts.map((account, i) => (
                  <div key={i} className="flex items-center justify-between rounded-md border p-3">
                    <span className="text-sm capitalize font-medium">{account.platform}</span>
                    <span className="text-sm text-muted-foreground">@{account.handle}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>

      <div className="flex justify-end mt-6">
        <Button type="submit" disabled={loading || !name}>
          <Save className="mr-2 h-4 w-4" />
          {loading ? "Saving..." : brand ? "Update Brand" : "Create Brand"}
        </Button>
      </div>
    </form>
  );
}
