"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  CheckCircle2, Circle, ChevronDown, ChevronRight, Sparkles,
  Building2, Image as ImageIcon, Mic2, Radio, ShoppingBag, Users, Rocket,
  Loader2, ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { Brand, Product } from "@/types";

interface BrandOnboardingProps {
  brand: Brand;
  onComplete: () => void;
  onNavigateTab?: (tab: string) => void;
  initialHasProducts?: boolean;
  initialCompetitorCount?: number;
}

interface StepDef {
  id: string;
  label: string;
  icon: React.ReactNode;
  description: string;
}

const STEPS: StepDef[] = [
  { id: "basic_info", label: "Basic Info", icon: <Building2 className="h-4 w-4" />, description: "Brand name and description" },
  { id: "business_central", label: "Business Central", icon: <Building2 className="h-4 w-4" />, description: "Link to Business Central company" },
  { id: "logos", label: "Logos", icon: <ImageIcon className="h-4 w-4" />, description: "Upload at least one brand logo" },
  { id: "voice_profile", label: "Voice Profile", icon: <Mic2 className="h-4 w-4" />, description: "Define your brand's tone of voice" },
  { id: "channels", label: "Channels", icon: <Radio className="h-4 w-4" />, description: "Enable and configure at least one channel" },
  { id: "products", label: "Products", icon: <ShoppingBag className="h-4 w-4" />, description: "Sync or add products" },
  { id: "competitors", label: "Competitors", icon: <Users className="h-4 w-4" />, description: "Track your competitors" },
  { id: "review", label: "Review & Activate", icon: <Rocket className="h-4 w-4" />, description: "Activate the content factory" },
];

export function BrandOnboarding({ brand, onComplete, onNavigateTab, initialHasProducts, initialCompetitorCount }: BrandOnboardingProps) {
  const [expandedStep, setExpandedStep] = useState<string | null>("basic_info");
  const [triggering, setTriggering] = useState<string | null>(null);
  const [activating, setActivating] = useState(false);
  const [hasProducts, setHasProducts] = useState(initialHasProducts ?? false);
  const [checkingProducts, setCheckingProducts] = useState(initialHasProducts === undefined);
  const [competitorCount, setCompetitorCount] = useState(initialCompetitorCount ?? 0);

  // Check if products exist
  useEffect(() => {
    async function checkProducts() {
      try {
        const products = await api.get<Product[]>(`/api/v1/products`, { brand_id: brand.id, limit: 1 });
        setHasProducts(products.length > 0);
      } catch {
        // ignore
      } finally {
        setCheckingProducts(false);
      }
    }
    checkProducts();
  }, [brand.id]);

  // Check if competitors exist
  useEffect(() => {
    api.get<unknown[]>(`/api/v1/brands/${brand.id}/competitors`)
      .then(data => setCompetitorCount(Array.isArray(data) ? data.length : 0))
      .catch(() => setCompetitorCount(0));
  }, [brand.id]);

  const logos = (brand.brand_guidelines as Record<string, unknown>)?.logos as Record<string, unknown> | undefined;
  const channels = (brand.brand_guidelines as Record<string, unknown>)?.channels as Record<string, { enabled?: boolean; configured?: boolean }> | undefined;
  const enabledChannels = channels
    ? Object.values(channels).filter((cfg) => cfg.enabled)
    : [];

  const stepComplete: Record<string, boolean> = {
    basic_info: !!(brand.name && brand.description),
    business_central: !!brand.bc_company,
    logos: !!(logos && Object.keys(logos).length > 0),
    voice_profile: !!brand.tone_of_voice,
    channels: enabledChannels.length > 0,
    products: hasProducts,
    competitors: competitorCount > 0,
    review: brand.is_active && !!(brand.name && brand.description),
  };

  // Count only setup steps (exclude "review" which is the activation action)
  const setupSteps = Object.entries(stepComplete).filter(([k]) => k !== "review");
  const completedCount = setupSteps.filter(([, v]) => v).length;
  const totalSteps = setupSteps.length;
  const requiredComplete = stepComplete.basic_info && stepComplete.voice_profile && stepComplete.channels && stepComplete.logos;
  const progressPercent = Math.round((completedCount / totalSteps) * 100);

  const handleAutoFillAll = async () => {
    setTriggering("autofill");
    try {
      const result = await api.post<{ fields: Record<string, string> }>(
        "/api/v1/intelligence/generate-fields",
        { brand_id: brand.id, field: null }
      );
      const count = Object.keys(result.fields).length;
      if (count === 0) {
        toast.info("All fields are already filled");
      } else {
        // Save generated fields to the brand
        const updates: Record<string, unknown> = {};
        if (result.fields.description) updates.description = result.fields.description;
        if (result.fields.tone_of_voice) updates.tone_of_voice = result.fields.tone_of_voice;
        if (result.fields.target_audience) updates.target_audience = { description: result.fields.target_audience };
        const guidelinesUpdate: Record<string, unknown> = { ...(brand.brand_guidelines || {}) };
        if (result.fields.voice_style) guidelinesUpdate.voice_style = result.fields.voice_style;
        if (result.fields.hashtag_strategy) guidelinesUpdate.hashtag_strategy = result.fields.hashtag_strategy;
        if (result.fields.dos) guidelinesUpdate.dos = result.fields.dos.split("\n").filter(Boolean);
        if (result.fields.donts) guidelinesUpdate.donts = result.fields.donts.split("\n").filter(Boolean);
        if (Object.keys(guidelinesUpdate).length > 0) updates.brand_guidelines = guidelinesUpdate;

        await api.put(`/api/v1/brands/${brand.id}`, updates);
        toast.success(`AI populated ${count} field${count !== 1 ? "s" : ""} — refresh to see changes`);
      }
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "AI generation failed";
      toast.error(detail);
    } finally {
      setTriggering(null);
    }
  };

  const handleSyncProducts = async () => {
    setTriggering("sync_products");
    try {
      await api.post(`/api/v1/products/sync/${brand.id}`);
      toast.success("Product sync started");
      setHasProducts(true);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to sync products";
      toast.error(detail);
    } finally {
      setTriggering(null);
    }
  };

  const handleActivate = async () => {
    setActivating(true);
    try {
      await api.post(`/api/v1/brands/${brand.id}/complete-onboarding`);
      await api.post(`/api/v1/brands/${brand.id}/activate`);
      toast.success("Content factory activated! AI agents are now working on your brand.");
      onComplete();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to activate content factory";
      toast.error(detail);
    } finally {
      setActivating(false);
    }
  };

  const toggleStep = (stepId: string) => {
    setExpandedStep(expandedStep === stepId ? null : stepId);
  };

  const renderStepContent = (stepId: string) => {
    switch (stepId) {
      case "basic_info": {
        const palette = brand.color_palette as { primary?: string; secondary?: string; accent?: string } | undefined;
        const hasColors = !!(palette?.primary || palette?.secondary || palette?.accent);
        return (
          <div className="space-y-3">
            <div className="text-sm">
              <span className="text-muted-foreground">Name:</span>{" "}
              <span className={brand.name ? "font-medium" : "text-muted-foreground italic"}>
                {brand.name || "Not set"}
              </span>
            </div>
            <div className="text-sm">
              <span className="text-muted-foreground">Description:</span>{" "}
              <span className={brand.description ? "font-medium" : "text-muted-foreground italic"}>
                {brand.description || "Not set"}
              </span>
            </div>
            <div className="text-sm">
              <span className="text-muted-foreground">Brand Colors:</span>{" "}
              {hasColors ? (
                <span className="inline-flex items-center gap-1.5 ml-1">
                  {(["primary", "secondary", "accent"] as const).map((key) => {
                    const hex = palette?.[key];
                    if (!hex) return null;
                    return (
                      <span
                        key={key}
                        className="inline-block h-4 w-4 rounded-full border border-border shadow-sm"
                        style={{ backgroundColor: hex }}
                        title={`${key}: ${hex}`}
                      />
                    );
                  })}
                </span>
              ) : (
                <span className="text-muted-foreground italic">Not set</span>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={triggering !== null}
                onClick={handleAutoFillAll}
              >
                {triggering === "autofill" ? (
                  <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-3 w-3" />
                )}
                Auto-fill with AI
              </Button>
              {onNavigateTab && (
                <Button size="sm" variant="ghost" onClick={() => onNavigateTab("edit")}>
                  Edit <ExternalLink className="ml-1 h-3 w-3" />
                </Button>
              )}
            </div>
          </div>
        );
      }

      case "business_central":
        return (
          <div className="space-y-3">
            <div className="text-sm">
              <span className="text-muted-foreground">BC Company:</span>{" "}
              <span className={brand.bc_company ? "font-medium" : "text-muted-foreground italic"}>
                {brand.bc_company || "Not linked"}
              </span>
            </div>
            {onNavigateTab && (
              <Button size="sm" variant="outline" onClick={() => onNavigateTab("edit")}>
                {brand.bc_company ? "Change BC Link" : "Link to Business Central"}
                <ExternalLink className="ml-1 h-3 w-3" />
              </Button>
            )}
          </div>
        );

      case "logos":
        return (
          <div className="space-y-3">
            <div className="text-sm">
              {logos && Object.keys(logos).length > 0 ? (
                <span className="font-medium">{Object.keys(logos).length} logo(s) uploaded</span>
              ) : (
                <span className="text-muted-foreground italic">No logos uploaded</span>
              )}
            </div>
            {onNavigateTab && (
              <Button size="sm" variant="outline" onClick={() => onNavigateTab("logos")}>
                Manage Logos <ExternalLink className="ml-1 h-3 w-3" />
              </Button>
            )}
          </div>
        );

      case "voice_profile":
        return (
          <div className="space-y-3">
            <div className="text-sm">
              <span className="text-muted-foreground">Tone of Voice:</span>{" "}
              <span className={brand.tone_of_voice ? "font-medium" : "text-muted-foreground italic"}>
                {brand.tone_of_voice || "Not set"}
              </span>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={triggering !== null}
                onClick={handleAutoFillAll}
              >
                {triggering === "autofill" ? (
                  <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-3 w-3" />
                )}
                Auto-fill with AI
              </Button>
              {onNavigateTab && (
                <Button size="sm" variant="ghost" onClick={() => onNavigateTab("edit")}>
                  Edit <ExternalLink className="ml-1 h-3 w-3" />
                </Button>
              )}
            </div>
          </div>
        );

      case "channels":
        return (
          <div className="space-y-3">
            <div className="text-sm">
              {enabledChannels.length > 0 ? (
                <span className="font-medium">{enabledChannels.length} channel(s) enabled and configured</span>
              ) : (
                <span className="text-muted-foreground italic">No channels configured</span>
              )}
            </div>
            {onNavigateTab && (
              <Button size="sm" variant="outline" onClick={() => onNavigateTab("channels")}>
                Configure Channels <ExternalLink className="ml-1 h-3 w-3" />
              </Button>
            )}
          </div>
        );

      case "products":
        return (
          <div className="space-y-3">
            <div className="text-sm">
              {checkingProducts ? (
                <span className="text-muted-foreground italic">Checking...</span>
              ) : hasProducts ? (
                <span className="font-medium">Products available</span>
              ) : (
                <span className="text-muted-foreground italic">No products yet</span>
              )}
            </div>
            <div className="flex gap-2">
              {brand.bc_company && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={triggering !== null}
                  onClick={handleSyncProducts}
                >
                  {triggering === "sync_products" ? (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  ) : (
                    <ShoppingBag className="mr-2 h-3 w-3" />
                  )}
                  Sync from BC
                </Button>
              )}
              {onNavigateTab && (
                <Button size="sm" variant="ghost" onClick={() => onNavigateTab("products")}>
                  View Products <ExternalLink className="ml-1 h-3 w-3" />
                </Button>
              )}
            </div>
            {!brand.bc_company && (
              <p className="text-xs text-muted-foreground">Link to Business Central first to sync products</p>
            )}
          </div>
        );

      case "competitors":
        return (
          <div className="space-y-3">
            <div className="text-sm">
              {competitorCount > 0 ? (
                <span className="font-medium">{competitorCount} competitor(s) tracked</span>
              ) : (
                <span className="text-muted-foreground italic">No competitors tracked</span>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={triggering !== null}
                onClick={async () => {
                  setTriggering("discover");
                  try {
                    const result = await api.post<{ fields: Record<string, string> }>("/api/v1/intelligence/generate-fields", {
                      brand_id: brand.id,
                      fields: ["competitors"],
                      context: `Brand: ${brand.name}. ${brand.description || ""}`,
                    });
                    const suggested = result.fields?.competitors;
                    if (suggested) {
                      toast.success("AI suggested competitors — add them using '+ Add Competitor'");
                      toast.info(suggested, { duration: 10000 });
                    } else {
                      toast.info("No competitor suggestions found. Add manually.");
                    }
                  } catch (err: unknown) {
                    const detail = (err as { detail?: string })?.detail || "Failed to discover competitors";
                    toast.error(detail);
                  } finally {
                    setTriggering(null);
                  }
                }}
              >
                {triggering === "discover" ? (
                  <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-3 w-3" />
                )}
                Auto-discover
              </Button>
              {onNavigateTab && (
                <Button size="sm" variant="ghost" onClick={() => onNavigateTab("competitors")}>
                  Manage Competitors <ExternalLink className="ml-1 h-3 w-3" />
                </Button>
              )}
            </div>
          </div>
        );

      case "review": {
        const requiredStepIds = ["basic_info", "voice_profile", "channels", "logos"];
        const missingSteps = STEPS.slice(0, 7).filter(
          (s) => requiredStepIds.includes(s.id) && !stepComplete[s.id]
        );
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              {STEPS.slice(0, 7).map((step) => {
                const isRecommended = step.id === "products" || step.id === "competitors" || step.id === "business_central";
                return (
                  <div key={step.id} className="flex items-center gap-2 text-sm">
                    {stepComplete[step.id] ? (
                      <CheckCircle2 className="h-4 w-4 text-green-500" />
                    ) : (
                      <Circle className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className={stepComplete[step.id] ? "text-foreground" : "text-muted-foreground"}>
                      {step.label}
                    </span>
                    {isRecommended ? (
                      <Badge variant="outline" className="text-[10px] ml-auto">Recommended</Badge>
                    ) : (
                      <Badge variant={stepComplete[step.id] ? "default" : "destructive"} className="text-[10px] ml-auto">
                        {stepComplete[step.id] ? "Complete" : "Required"}
                      </Badge>
                    )}
                  </div>
                );
              })}
            </div>
            {!requiredComplete && (
              <p className="text-sm text-destructive">
                Missing required steps: {missingSteps.map((s) => s.label).join(", ")}
              </p>
            )}
            <Button
              size="lg"
              className="w-full"
              disabled={!requiredComplete || activating}
              onClick={handleActivate}
            >
              {activating ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Rocket className="mr-2 h-4 w-4" />
              )}
              {activating ? "Activating..." : "Start Content Factory"}
            </Button>
          </div>
        );
      }

      default:
        return null;
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Brand Onboarding</CardTitle>
          <Badge variant="outline">{completedCount}/{totalSteps} steps</Badge>
        </div>
        {/* Progress bar */}
        <div className="w-full bg-muted rounded-full h-2 mt-2">
          <div
            className="bg-primary h-2 rounded-full transition-all duration-500"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex gap-6">
          {/* Left: Vertical stepper */}
          <div className="hidden md:flex flex-col gap-1 min-w-[200px]">
            {STEPS.map((step, idx) => {
              const isComplete = stepComplete[step.id];
              const isActive = expandedStep === step.id;
              return (
                <button
                  key={step.id}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md text-left text-sm transition-colors ${
                    isActive
                      ? "bg-primary/10 text-primary font-medium"
                      : "hover:bg-muted text-muted-foreground"
                  }`}
                  onClick={() => toggleStep(step.id)}
                >
                  {isComplete ? (
                    <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                  ) : (
                    <span className="flex h-4 w-4 items-center justify-center rounded-full border text-[10px] shrink-0">
                      {idx + 1}
                    </span>
                  )}
                  <span className="truncate">{step.label}</span>
                </button>
              );
            })}
          </div>

          {/* Right: Content area (or full width on mobile) */}
          <div className="flex-1 space-y-2">
            {STEPS.map((step) => {
              const isComplete = stepComplete[step.id];
              const isExpanded = expandedStep === step.id;
              return (
                <div key={step.id} className="border rounded-lg">
                  <button
                    className="flex items-center gap-3 w-full px-4 py-3 text-left"
                    onClick={() => toggleStep(step.id)}
                  >
                    {isComplete ? (
                      <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
                    ) : (
                      <Circle className="h-5 w-5 text-muted-foreground shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{step.label}</p>
                      <p className="text-xs text-muted-foreground">{step.description}</p>
                    </div>
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                    )}
                  </button>
                  {isExpanded && (
                    <div className="px-4 pb-4 pt-1 border-t">
                      {renderStepContent(step.id)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
