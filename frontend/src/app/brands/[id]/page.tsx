"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  ArrowLeft, Trash2,
  Instagram, Facebook, Linkedin, Youtube, Music2, Twitter, Globe,
  MessageSquare,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { BrandOnboarding } from "@/components/brand/BrandOnboarding";
import { api, apiUrl } from "@/lib/api";
import type { Brand, Content, EngagementMetrics, Channel, Product, AgentRun } from "@/types";

import {
  OverviewTab,
  ChannelsTab,
  LogosTab,
  IntelligenceTab,
  ProductsTab,
  EditBrandTab,
  CompetitorsTab,
  PerformanceTab,
} from "@/components/brand/tabs";

const ALL_CHANNELS: Channel[] = [
  "instagram", "facebook", "linkedin", "youtube",
  "tiktok", "x", "website_blog", "teams",
];

const CHANNEL_ICON_STYLED: Record<string, { icon: React.ReactNode; color: string }> = {
  instagram: { icon: <Instagram className="h-4 w-4" />, color: "bg-linear-to-br from-purple-500 via-pink-500 to-orange-400 text-white" },
  facebook: { icon: <Facebook className="h-4 w-4" />, color: "bg-[#1877F2] text-white" },
  linkedin: { icon: <Linkedin className="h-4 w-4" />, color: "bg-[#0A66C2] text-white" },
  youtube: { icon: <Youtube className="h-4 w-4" />, color: "bg-[#FF0000] text-white" },
  tiktok: { icon: <Music2 className="h-4 w-4" />, color: "bg-black text-white dark:bg-white dark:text-black" },
  x: { icon: <Twitter className="h-4 w-4" />, color: "bg-black text-white dark:bg-white dark:text-black" },
  website_blog: { icon: <Globe className="h-4 w-4" />, color: "bg-emerald-600 text-white" },
  teams: { icon: <MessageSquare className="h-4 w-4" />, color: "bg-[#6264A7] text-white" },
};

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

interface LogoInfo {
  url: string;
  label: string;
  filename?: string;
}

interface CompetitorData {
  id: string;
  name: string;
  website_url?: string;
  social_handles: Record<string, string>;
  notes?: string;
}

export default function BrandDetailPage() {
  const params = useParams();
  const router = useRouter();
  const brandId = params.id as string;

  // AbortController ref to cancel in-flight requests on brand switch / unmount
  const abortRef = useRef<AbortController | null>(null);

  const [brand, setBrand] = useState<Brand | null>(null);
  const [content, setContent] = useState<Content[]>([]);
  const [metrics, setMetrics] = useState<EngagementMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [channelConfigs, setChannelConfigs] = useState<Record<string, ChannelConfig>>({});
  const [expandedChannel, setExpandedChannel] = useState<string | null>(null);
  const [savingChannels, setSavingChannels] = useState(false);

  // Logo state
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [selectedLogoLabel, setSelectedLogoLabel] = useState("primary");

  // Intelligence state
  const [research, setResearch] = useState<AgentRun[]>([]);
  const [competitors, setCompetitors] = useState<CompetitorData[]>([]);
  const [loadingIntel, setLoadingIntel] = useState(false);
  const [triggeringWorkflow, setTriggeringWorkflow] = useState<string | null>(null);

  // Products state
  const [products, setProducts] = useState<Product[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [syncingProducts, setSyncingProducts] = useState(false);
  const [productFilter, setProductFilter] = useState<{
    category: string;
    stockLevel: string;
    newOnly: boolean;
    expiringOnly: boolean;
  }>({ category: "", stockLevel: "all", newOnly: false, expiringOnly: false });
  const [togglingProduct, setTogglingProduct] = useState<string | null>(null);
  const [expandedProductId, setExpandedProductId] = useState<string | null>(null);
  const [fetchingImages, setFetchingImages] = useState<string | null>(null);
  const [galleryProduct, setGalleryProduct] = useState<Product | null>(null);
  const [galleryImages, setGalleryImages] = useState<{ url: string; object_name?: string; source?: string }[]>([]);
  const [galleryLoading, setGalleryLoading] = useState(false);
  const [selectedProductIds, setSelectedProductIds] = useState<Set<string>>(new Set());

  // Tab state
  const [activeTab, setActiveTab] = useState("overview");

  // Onboarding dialog state
  const [onboardingOpen, setOnboardingOpen] = useState(false);

  // Delete confirmation dialog state
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // Agent Pipeline state
  const [pipelineRuns, setPipelineRuns] = useState<AgentRun[]>([]);
  const [loadingPipeline, setLoadingPipeline] = useState(false);
  const [togglingFactory, setTogglingFactory] = useState(false);

  // Abort previous requests and create new controller on each fetch cycle
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    async function fetchData() {
      try {
        const [brandData, contentData, metricsData] = await Promise.allSettled([
          api.get<Brand>(`/api/v1/brands/${brandId}`, undefined, { signal }),
          api.get<Content[]>(`/api/v1/content`, { brand_id: brandId, limit: 20 }, { signal }),
          api.get<EngagementMetrics>(`/api/v1/analytics/brands/${brandId}/metrics`, undefined, { signal }),
        ]);

        if (brandData.status === "fulfilled") {
          setBrand(brandData.value);
          const guidelines = brandData.value.brand_guidelines || {};
          const channels = (guidelines as Record<string, unknown>).channels as Record<string, ChannelConfig> | undefined;
          if (channels) {
            setChannelConfigs(channels);
          }
        }
        if (contentData.status === "fulfilled") setContent(contentData.value);
        if (metricsData.status === "fulfilled") setMetrics(metricsData.value);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        toast.error("Failed to load brand data");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
    // Also fetch products for onboarding progress calculation
    api.get<Product[]>("/api/v1/products", { brand_id: brandId }, { signal }).then(setProducts).catch(() => {});
    // Fetch pipeline runs for Overview tab
    api.get<AgentRun[]>("/api/v1/agents/runs", { brand_id: brandId, limit: 20 }, { signal }).then(setPipelineRuns).catch(() => {});

    return () => {
      abortRef.current?.abort();
    };
  }, [brandId]);

  const fetchIntelligence = useCallback(async () => {
    setLoadingIntel(true);
    try {
      const [runsData, compData] = await Promise.allSettled([
        api.get<AgentRun[]>("/api/v1/agents/runs", { brand_id: brandId, limit: 20 }),
        api.get<{ competitors: CompetitorData[] }>(`/api/v1/intelligence/research/${brandId}`),
      ]);
      if (runsData.status === "fulfilled") {
        setResearch(runsData.value);
        setPipelineRuns(runsData.value);
      }
      if (compData.status === "fulfilled") {
        setCompetitors(compData.value.competitors || []);
      }
    } catch {
      // Intelligence data is optional
    } finally {
      setLoadingIntel(false);
    }
  }, [brandId]);

  // Poll for updates when on intelligence/overview tab and runs are active
  useEffect(() => {
    const hasRunning = research.some((r) => r.status === "running" || r.status === "pending");
    if (!hasRunning || (activeTab !== "intelligence" && activeTab !== "overview")) return;
    const interval = setInterval(() => {
      api.get<AgentRun[]>("/api/v1/agents/runs", { brand_id: brandId, limit: 20 })
        .then((runs) => {
          setResearch(runs);
          setPipelineRuns(runs);
        })
        .catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, [research, activeTab, brandId]);

  const fetchPipelineRuns = useCallback(async () => {
    setLoadingPipeline(true);
    try {
      const runs = await api.get<AgentRun[]>(`/api/v1/agents/runs`, { brand_id: brandId, limit: 20 });
      setPipelineRuns(runs);
    } catch {
      // Pipeline data is optional
    } finally {
      setLoadingPipeline(false);
    }
  }, [brandId]);

  const handleToggleContentFactory = useCallback(async (turnOn: boolean) => {
    setTogglingFactory(true);
    try {
      if (turnOn) {
        await api.post(`/api/v1/brands/${brandId}/activate`);
        toast.success("Content Factory started. AI agents are now working on your brand.");
        const updated = await api.get<Brand>(`/api/v1/brands/${brandId}`);
        setBrand(updated);
        setTimeout(fetchPipelineRuns, 3000);
      } else {
        await api.put(`/api/v1/brands/${brandId}`, { is_active: false });
        const updated = await api.get<Brand>(`/api/v1/brands/${brandId}`);
        setBrand(updated);
        toast.success("Content Factory stopped. Running agents have been cancelled.");
        setTimeout(fetchPipelineRuns, 1000);
      }
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to toggle Content Factory";
      toast.error(detail);
    } finally {
      setTogglingFactory(false);
    }
  }, [brandId, fetchPipelineRuns]);

  const handleSave = useCallback(async (data: Partial<Brand>) => {
    setSaving(true);
    try {
      const updated = await api.put<Brand>(`/api/v1/brands/${brandId}`, data);
      setBrand(updated);
      toast.success("Brand updated successfully");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update brand";
      toast.error(detail);
    } finally {
      setSaving(false);
    }
  }, [brandId]);

  const toggleChannelEnabled = useCallback((ch: string, enabled: boolean) => {
    setChannelConfigs((prev) => ({
      ...prev,
      [ch]: { ...prev[ch], enabled, configured: prev[ch]?.configured ?? false },
    }));
  }, []);

  const updateChannelField = useCallback((ch: string, key: string, value: string) => {
    setChannelConfigs((prev) => ({
      ...prev,
      [ch]: { ...prev[ch], [key]: value },
    }));
  }, []);

  const handleSaveChannels = useCallback(async () => {
    // Validate: check enabled channels have required fields
    const updatedConfigs = { ...channelConfigs };
    for (const ch of ALL_CHANNELS) {
      const cfg = updatedConfigs[ch];
      if (!cfg?.enabled) continue;
      const fields = CHANNEL_CONFIG_FIELDS[ch];
      const hasAllFields = fields.every((f) => {
        if (f.label.includes("optional")) return true;
        return !!(cfg as Record<string, unknown>)[f.key];
      });
      updatedConfigs[ch] = { ...cfg, configured: hasAllFields };
    }

    setSavingChannels(true);
    try {
      const result = await api.put<{ status: string; channels: Record<string, ChannelConfig> }>(
        `/api/v1/brands/${brandId}/channels`,
        { channels: updatedConfigs }
      );
      if (result.channels) {
        setChannelConfigs(result.channels);
      }
      const updated = await api.get<Brand>(`/api/v1/brands/${brandId}`);
      setBrand(updated);
      toast.success("Channel configuration saved");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to save channel configuration";
      toast.error(detail);
    } finally {
      setSavingChannels(false);
    }
  }, [brandId, channelConfigs]);

  const handleDelete = useCallback(async () => {
    try {
      await api.delete(`/api/v1/brands/${brandId}`);
      toast.success("Brand deleted");
      router.push("/brands");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to delete brand";
      toast.error(detail);
    }
  }, [brandId, router]);

  const handleLogoUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      toast.error("Logo must be under 5MB");
      return;
    }

    const allowed = ["image/png", "image/jpeg", "image/svg+xml", "image/webp"];
    if (!allowed.includes(file.type)) {
      toast.error("Only PNG, JPEG, SVG, and WebP images are allowed");
      return;
    }

    setUploadingLogo(true);
    try {
      await api.uploadFile<{ logos: Record<string, LogoInfo> }>(
        `/api/v1/brands/${brandId}/logos?label=${selectedLogoLabel}`,
        file
      );
      const updated = await api.get<Brand>(`/api/v1/brands/${brandId}`);
      setBrand(updated);
      toast.success("Logo uploaded");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to upload logo";
      toast.error(detail);
    } finally {
      setUploadingLogo(false);
      e.target.value = "";
    }
  }, [brandId, selectedLogoLabel]);

  const handleDeleteLogo = useCallback(async (label: string) => {
    try {
      await api.delete(`/api/v1/brands/${brandId}/logos/${label}`);
      const updated = await api.get<Brand>(`/api/v1/brands/${brandId}`);
      setBrand(updated);
      toast.success("Logo removed");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to delete logo";
      toast.error(detail);
    }
  }, [brandId]);

  const handleTriggerWorkflow = useCallback(async (workflowType: string) => {
    setTriggeringWorkflow(workflowType);
    try {
      await api.post(`/api/v1/intelligence/trigger/${workflowType}`, { brand_id: brandId });
      toast.success(`${workflowType.charAt(0).toUpperCase() + workflowType.slice(1)} workflow triggered`);
      setTimeout(fetchIntelligence, 2000);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || `Failed to trigger ${workflowType}`;
      toast.error(detail);
    } finally {
      setTriggeringWorkflow(null);
    }
  }, [brandId, fetchIntelligence]);

  // Auto-open onboarding dialog when brand is in onboarding status
  useEffect(() => {
    if (brand && brand.status === 'onboarding') {
      setOnboardingOpen(true);
    }
  }, [brand?.status]);

  // Compute onboarding progress
  const onboardingProgress = (() => {
    if (!brand) return { completed: 0, total: 7, isComplete: false };
    const guidelines = (brand.brand_guidelines || {}) as Record<string, unknown>;
    const logos = guidelines.logos as Record<string, unknown> | undefined;
    const channels = guidelines.channels as Record<string, { enabled?: boolean; configured?: boolean }> | undefined;
    const configuredChannels = channels ? Object.values(channels).filter((c) => c.enabled && c.configured) : [];
    const checks = [
      !!(brand.name && brand.description),
      !!brand.bc_company,
      !!(logos && Object.keys(logos).length > 0),
      !!brand.tone_of_voice,
      configuredChannels.length > 0,
      products.length > 0,
      !!(brand.competitors && brand.competitors.length > 0),
    ];
    const completed = checks.filter(Boolean).length;
    return { completed, total: checks.length, isComplete: completed === checks.length };
  })();

  // Products fetching
  const fetchProducts = useCallback(async () => {
    if (!brandId) return;
    setLoadingProducts(true);
    try {
      const data = await api.get<Product[]>(`/api/v1/products`, { brand_id: brandId });
      setProducts(data);
    } catch {
      // Products data is optional
    } finally {
      setLoadingProducts(false);
    }
  }, [brandId]);

  const handleSyncProducts = useCallback(async () => {
    setSyncingProducts(true);
    try {
      const result = await api.post<{ message: string }>(`/api/v1/products/sync/${brandId}`);
      toast.success(result.message || "Products synced successfully");
      await fetchProducts();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to sync products";
      toast.error(detail);
    } finally {
      setSyncingProducts(false);
    }
  }, [brandId, fetchProducts]);

  const handleToggleProductActive = useCallback(async (productId: string, isActive: boolean) => {
    setTogglingProduct(productId);
    try {
      const updated = await api.put<Product>(`/api/v1/products/${productId}`, { is_active: isActive });
      setProducts((prev) => prev.map((p) => (p.id === productId ? updated : p)));
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update product";
      toast.error(detail);
    } finally {
      setTogglingProduct(null);
    }
  }, []);

  const getFilteredProducts = useCallback(() => {
    let filtered = products;
    if (productFilter.category) {
      filtered = filtered.filter((p) => p.category === productFilter.category);
    }
    if (productFilter.stockLevel === "in-stock") {
      filtered = filtered.filter((p) => (p.remaining_qty ?? 0) > 10);
    } else if (productFilter.stockLevel === "low") {
      filtered = filtered.filter((p) => (p.remaining_qty ?? 0) > 0 && (p.remaining_qty ?? 0) <= 10);
    } else if (productFilter.stockLevel === "out") {
      filtered = filtered.filter((p) => (p.remaining_qty ?? 0) <= 0);
    }
    if (productFilter.newOnly) {
      filtered = filtered.filter((p) => p.is_new);
    }
    if (productFilter.expiringOnly) {
      filtered = filtered.filter((p) => p.is_expiring_soon);
    }
    return filtered;
  }, [products, productFilter]);

  const handleBulkProductActive = useCallback(async (isActive: boolean) => {
    const filtered = getFilteredProducts();
    for (const product of filtered) {
      if (product.is_active !== isActive) {
        try {
          await api.put<Product>(`/api/v1/products/${product.id}`, { is_active: isActive });
        } catch {
          // continue
        }
      }
    }
    await fetchProducts();
    toast.success(isActive ? "All visible products included" : "All visible products excluded");
  }, [getFilteredProducts, fetchProducts]);

  const productCategories = [...new Set(products.map((p) => p.category).filter(Boolean))] as string[];

  // Image gallery handlers
  const openGallery = useCallback(async (product: Product) => {
    setGalleryProduct(product);
    setGalleryLoading(true);
    try {
      const res = await api.get<{ images: { url: string; object_name?: string; source?: string }[]; primary_image_url: string | null }>(
        `/api/v1/products/${product.id}/images`
      );
      setGalleryImages(res.images || []);
    } catch {
      setGalleryImages(Array.isArray(product.image_urls) ? product.image_urls : []);
    } finally {
      setGalleryLoading(false);
    }
  }, []);

  const handleDeleteGalleryImage = useCallback(async (index: number) => {
    if (!galleryProduct) return;
    try {
      await api.delete(`/api/v1/products/${galleryProduct.id}/images/${index}`);
      setGalleryImages((prev) => prev.filter((_, i) => i !== index));
      toast.success("Image removed");
      fetchProducts();
    } catch {
      toast.error("Failed to remove image");
    }
  }, [galleryProduct, fetchProducts]);

  const handleSetPrimaryImage = useCallback(async (index: number) => {
    if (!galleryProduct) return;
    try {
      await api.put(`/api/v1/products/${galleryProduct.id}/images/${index}/set-primary`);
      toast.success("Primary image updated");
      fetchProducts();
    } catch {
      toast.error("Failed to set primary image");
    }
  }, [galleryProduct, fetchProducts]);

  const handleUploadProductImage = useCallback(async (file: File) => {
    if (!galleryProduct) return;
    try {
      await api.uploadFile(`/api/v1/products/${galleryProduct.id}/upload-image`, file);
      toast.success("Image uploaded");
      openGallery(galleryProduct);
      fetchProducts();
    } catch {
      toast.error("Failed to upload image");
    }
  }, [galleryProduct, openGallery, fetchProducts]);

  const handleBatchFetchSelected = useCallback(async () => {
    const ids = Array.from(selectedProductIds);
    if (ids.length === 0) { toast.info("Select products first"); return; }
    setFetchingImages("batch-selected");
    try {
      const res = await api.post<{ results: { product_id: string; images_found: number }[] }>(
        "/api/v1/products/batch-fetch-images",
        { product_ids: ids }
      );
      const total = res.results.reduce((s, r) => s + (r.images_found || 0), 0);
      toast.success(`Found ${total} images for ${res.results.length} products`);
      fetchProducts();
      setSelectedProductIds(new Set());
    } catch {
      toast.error("Failed to fetch images");
    } finally {
      setFetchingImages(null);
    }
  }, [selectedProductIds, fetchProducts]);

  const handleBatchFetchNoImage = useCallback(async () => {
    const activeProducts = getFilteredProducts().filter((p) => p.is_active && !p.primary_image_url);
    if (activeProducts.length === 0) {
      toast.info("All active products already have images");
      return;
    }
    setFetchingImages("batch");
    try {
      const res = await api.post<{ results: { product_id: string; images_found: number }[] }>(
        "/api/v1/products/batch-fetch-images",
        { product_ids: activeProducts.slice(0, 10).map((p) => p.id) }
      );
      const total = res.results.reduce((sum, r) => sum + r.images_found, 0);
      toast.success(`Found ${total} images for ${res.results.length} products`);
      fetchProducts();
    } catch {
      toast.error("Failed to fetch product images");
    } finally {
      setFetchingImages(null);
    }
  }, [getFilteredProducts, fetchProducts]);

  const toggleProductSelection = useCallback((id: string) => {
    setSelectedProductIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const handleOnboardingComplete = useCallback(async () => {
    const updated = await api.get<Brand>(`/api/v1/brands/${brandId}`);
    setBrand(updated);
    const guidelines = updated.brand_guidelines || {};
    const chs = (guidelines as Record<string, unknown>).channels as Record<string, ChannelConfig> | undefined;
    if (chs) setChannelConfigs(chs);
    setOnboardingOpen(false);
    setActiveTab("overview");
  }, [brandId]);

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

  const logos = (brand.brand_guidelines as Record<string, unknown>)?.logos as Record<string, LogoInfo> | undefined;
  const enabledChannels = Object.entries(channelConfigs).filter(([, cfg]) => cfg.enabled);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push("/brands")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-3">
            {brand.logo_url && (
              <img
                src={apiUrl(brand.logo_url)}
                alt={brand.name}
                className="h-10 w-10 rounded-lg object-cover border"
                loading="lazy"
              />
            )}
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-3xl font-bold">{brand.name}</h1>
                {brand.status === 'active' ? (
                  <span className="h-2.5 w-2.5 rounded-full bg-green-500" title="Active" />
                ) : brand.status === 'activating' ? (
                  <span className="h-2.5 w-2.5 rounded-full bg-cyan-500 animate-pulse" title="Setting up..." />
                ) : brand.status === 'onboarding' ? (
                  <span className="h-2.5 w-2.5 rounded-full bg-orange-500" title="Setup required" />
                ) : (
                  <span className="h-2.5 w-2.5 rounded-full bg-gray-400" title="Inactive" />
                )}
              </div>
              {brand.description && (
                <p className="text-sm text-muted-foreground">{brand.description}</p>
              )}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="destructive" size="sm" onClick={() => setDeleteConfirmOpen(true)}>
            <Trash2 className="mr-2 h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={(val) => {
        setActiveTab(val);
        if (val === "intelligence" && research.length === 0) fetchIntelligence();
        if (val === "products" && products.length === 0) fetchProducts();
        if (val === "overview") fetchPipelineRuns();
      }}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="channels">Channels</TabsTrigger>
          <TabsTrigger value="logos">Logos</TabsTrigger>
          <TabsTrigger value="intelligence">Intelligence</TabsTrigger>
          <TabsTrigger value="products">Products</TabsTrigger>
          <TabsTrigger value="edit">Edit Brand</TabsTrigger>
          <TabsTrigger value="competitors">Competitors</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab
            brand={brand}
            content={content}
            metrics={metrics}
            channelConfigs={channelConfigs}
            channelIconStyled={CHANNEL_ICON_STYLED}
            channelDisplayNames={CHANNEL_DISPLAY_NAMES}
            enabledChannels={enabledChannels}
            pipelineRuns={pipelineRuns}
            loadingPipeline={loadingPipeline}
            togglingFactory={togglingFactory}
            onboardingProgress={onboardingProgress}
            onOpenOnboarding={() => setOnboardingOpen(true)}
            onToggleContentFactory={handleToggleContentFactory}
            onFetchPipelineRuns={fetchPipelineRuns}
            onSetActiveTab={setActiveTab}
            onFetchIntelligence={fetchIntelligence}
            research={research}
          />
        </TabsContent>

        <TabsContent value="channels">
          <ChannelsTab
            channelConfigs={channelConfigs}
            expandedChannel={expandedChannel}
            savingChannels={savingChannels}
            allChannels={ALL_CHANNELS}
            channelIconStyled={CHANNEL_ICON_STYLED}
            channelDisplayNames={CHANNEL_DISPLAY_NAMES}
            channelConfigFields={CHANNEL_CONFIG_FIELDS}
            onToggleChannelEnabled={toggleChannelEnabled}
            onUpdateChannelField={updateChannelField}
            onSetExpandedChannel={setExpandedChannel}
            onSaveChannels={handleSaveChannels}
          />
        </TabsContent>

        <TabsContent value="logos">
          <LogosTab
            logos={logos}
            uploadingLogo={uploadingLogo}
            selectedLogoLabel={selectedLogoLabel}
            onSetSelectedLogoLabel={setSelectedLogoLabel}
            onLogoUpload={handleLogoUpload}
            onDeleteLogo={handleDeleteLogo}
          />
        </TabsContent>

        <TabsContent value="intelligence">
          <IntelligenceTab
            research={research}
            competitors={competitors}
            loadingIntel={loadingIntel}
            triggeringWorkflow={triggeringWorkflow}
            onTriggerWorkflow={handleTriggerWorkflow}
          />
        </TabsContent>

        <TabsContent value="products">
          <ProductsTab
            brand={brand}
            products={products}
            loadingProducts={loadingProducts}
            syncingProducts={syncingProducts}
            productFilter={productFilter}
            togglingProduct={togglingProduct}
            expandedProductId={expandedProductId}
            fetchingImages={fetchingImages}
            galleryProduct={galleryProduct}
            galleryImages={galleryImages}
            galleryLoading={galleryLoading}
            selectedProductIds={selectedProductIds}
            productCategories={productCategories}
            onSetActiveTab={setActiveTab}
            onSyncProducts={handleSyncProducts}
            onSetProductFilter={setProductFilter}
            onToggleProductActive={handleToggleProductActive}
            onBulkProductActive={handleBulkProductActive}
            onSetExpandedProductId={setExpandedProductId}
            onOpenGallery={openGallery}
            onDeleteGalleryImage={handleDeleteGalleryImage}
            onSetPrimaryImage={handleSetPrimaryImage}
            onUploadProductImage={handleUploadProductImage}
            onSetGalleryProduct={setGalleryProduct}
            onToggleProductSelection={toggleProductSelection}
            onSetSelectedProductIds={setSelectedProductIds}
            onBatchFetchSelected={handleBatchFetchSelected}
            onBatchFetchNoImage={handleBatchFetchNoImage}
            getFilteredProducts={getFilteredProducts}
          />
        </TabsContent>

        <TabsContent value="edit">
          <EditBrandTab
            brand={brand}
            saving={saving}
            onSave={handleSave}
          />
        </TabsContent>

        <TabsContent value="competitors">
          <CompetitorsTab
            brandId={brandId}
            competitors={brand.competitors || []}
          />
        </TabsContent>

        <TabsContent value="performance">
          <PerformanceTab metrics={metrics} />
        </TabsContent>
      </Tabs>

      {/* Onboarding Dialog */}
      <Dialog open={onboardingOpen} onOpenChange={setOnboardingOpen}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto" aria-describedby={undefined}>
          <DialogTitle className="sr-only">Brand Setup</DialogTitle>
          <BrandOnboarding
            brand={brand}
            onComplete={handleOnboardingComplete}
            onNavigateTab={(tab) => {
              setOnboardingOpen(false);
              setActiveTab(tab);
            }}
          />
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title="Delete Brand"
        description="Are you sure you want to delete this brand? This action cannot be undone."
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={handleDelete}
      />
    </div>
  );
}
