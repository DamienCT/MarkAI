"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ShoppingBag, RefreshCw, Loader2, Search, Upload, ImageIcon,
  CheckCircle2, Trash2, ChevronDown, ChevronLeft, ChevronRight,
  Tag, RotateCw, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuCheckboxItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { formatRelativeTime } from "@/lib/utils";
import { api, fileUrl } from "@/lib/api";
import type { Brand, Product } from "@/types";

type SyncOption = { value: string; label: string };
type SyncOptionsResponse = {
  vendors: { no: string; name: string }[];
  categories: { code: string; description: string }[];
  selected_vendor_nos?: string[];
  selected_categories?: string[];
};

const PAGE_SIZE = 50;

export interface ProductsTabProps {
  brand: Brand;
  products: Product[];
  loadingProducts: boolean;
  syncingProducts: boolean;
  productFilter: {
    category: string;
    stockLevel: string;
    newOnly: boolean;
    expiringOnly: boolean;
    vendors: string[];
  };
  togglingProduct: string | null;
  expandedProductId: string | null;
  fetchingImages: string | null;
  galleryProduct: Product | null;
  galleryImages: { url: string; object_name?: string; source?: string }[];
  galleryLoading: boolean;
  selectedProductIds: Set<string>;
  productCategories: string[];
  productVendors: string[];
  onSetActiveTab: (tab: string) => void;
  onSyncProducts: (vendorNos?: string[] | null, categories?: string[] | null) => Promise<void>;
  onSetProductFilter: (updater: (prev: ProductsTabProps["productFilter"]) => ProductsTabProps["productFilter"]) => void;
  onToggleProductActive: (productId: string, isActive: boolean) => Promise<void>;
  onBulkProductActive: (isActive: boolean) => Promise<void>;
  onSetExpandedProductId: (id: string | null) => void;
  onOpenGallery: (product: Product) => Promise<void>;
  onDeleteGalleryImage: (index: number) => Promise<void>;
  onSetPrimaryImage: (index: number) => Promise<void>;
  onUploadProductImage: (file: File) => Promise<void>;
  onSetGalleryProduct: (product: Product | null) => void;
  onToggleProductSelection: (id: string) => void;
  onSetSelectedProductIds: (ids: Set<string>) => void;
  onBatchFetchSelected: () => Promise<void>;
  onBatchFetchNoImage: () => Promise<void>;
  onSearchWebImages: (product: Product) => Promise<void>;
  getFilteredProducts: () => Product[];
}

export function ProductsTab({
  brand,
  products,
  loadingProducts,
  syncingProducts,
  productFilter,
  togglingProduct,
  expandedProductId,
  fetchingImages,
  galleryProduct,
  galleryImages,
  galleryLoading,
  selectedProductIds,
  productCategories,
  productVendors,
  onSetActiveTab,
  onSyncProducts,
  onSetProductFilter,
  onToggleProductActive,
  onBulkProductActive,
  onSetExpandedProductId,
  onOpenGallery,
  onDeleteGalleryImage,
  onSetPrimaryImage,
  onUploadProductImage,
  onSetGalleryProduct,
  onToggleProductSelection,
  onSetSelectedProductIds,
  onBatchFetchSelected,
  onBatchFetchNoImage,
  onSearchWebImages,
  getFilteredProducts,
}: ProductsTabProps) {
  // Pagination state — applied after filtering
  const [page, setPage] = useState(1);
  const filteredProducts = getFilteredProducts();
  const totalPages = Math.max(1, Math.ceil(filteredProducts.length / PAGE_SIZE));
  // Reset to page 1 when filters / dataset reduce the list below current page
  useEffect(() => {
    if (page > totalPages) setPage(1);
  }, [page, totalPages]);
  const pagedProducts = useMemo(
    () => filteredProducts.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filteredProducts, page]
  );

  // Sync dialog state
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);
  const [syncOptionsLoading, setSyncOptionsLoading] = useState(false);
  const [vendorOptions, setVendorOptions] = useState<SyncOption[]>([]);
  const [categoryOptions, setCategoryOptions] = useState<SyncOption[]>([]);
  const [selectedVendors, setSelectedVendors] = useState<Set<string>>(new Set());
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set());
  const [vendorSearch, setVendorSearch] = useState("");
  const [categorySearch, setCategorySearch] = useState("");

  // Vendor logo modal — logos belong to the vendor (manufacturer), keyed by
  // vendor_name and stored at the brand level. One logo covers all of that
  // vendor's products at generation time.
  type VendorVariant = "light" | "dark";
  type VendorLogo = {
    vendor_name: string;
    has_logo: boolean;
    logo_url: string | null;
    light_url: string | null;
    dark_url: string | null;
  };
  const [vendorLogoOpen, setVendorLogoOpen] = useState(false);
  const [vendorLogos, setVendorLogos] = useState<VendorLogo[]>([]);
  const [vendorLogosLoading, setVendorLogosLoading] = useState(false);
  const [vendorLogoBusy, setVendorLogoBusy] = useState<string | null>(null);
  const vendorAttempts = useRef<Record<string, number>>({});

  // Category logos — fallback logo keyed by the product's category code (e.g.
  // "REUS-WEAR"), used at render time when a product's vendor has no logo.
  type CategoryLogo = {
    category: string;
    has_logo: boolean;
    logo_url: string | null;
    light_url: string | null;
    dark_url: string | null;
  };
  const [categoryLogos, setCategoryLogos] = useState<CategoryLogo[]>([]);
  const [categoryLogosLoading, setCategoryLogosLoading] = useState(false);
  const [categoryLogoBusy, setCategoryLogoBusy] = useState<string | null>(null);
  const categoryAttempts = useRef<Record<string, number>>({});
  // Bumped on every (re)load so the <img> URL changes after a fetch/upload —
  // a vendor's logo object name is stable, so without this the browser would
  // keep showing the previously cached image even after it was replaced.
  const [logoVersion, setLogoVersion] = useState(0);

  const loadVendorLogos = async () => {
    setVendorLogosLoading(true);
    try {
      const data = await api.get<{ vendors: VendorLogo[] }>(
        `/api/v1/brands/${brand.id}/vendors`
      );
      setVendorLogos(data.vendors || []);
      setLogoVersion((v) => v + 1);
    } catch {
      toast.error("Failed to load vendors");
    } finally {
      setVendorLogosLoading(false);
    }
  };

  const loadCategoryLogos = async () => {
    setCategoryLogosLoading(true);
    try {
      const data = await api.get<{ categories: CategoryLogo[] }>(
        `/api/v1/brands/${brand.id}/categories`
      );
      setCategoryLogos(data.categories || []);
      setLogoVersion((v) => v + 1);
    } catch {
      toast.error("Failed to load categories");
    } finally {
      setCategoryLogosLoading(false);
    }
  };

  const openVendorLogos = () => {
    setVendorLogoOpen(true);
    vendorAttempts.current = {};
    categoryAttempts.current = {};
    loadVendorLogos();
    loadCategoryLogos();
  };

  // Busy key is per vendor+variant so the two slots spin independently.
  const _busyKey = (vendorName: string, variant: VendorVariant) => `${vendorName}:${variant}`;

  const fetchVendorLogo = async (vendorName: string, variant: VendorVariant, retry: boolean) => {
    const key = _busyKey(vendorName, variant);
    const cur = vendorAttempts.current[key] ?? -1;
    const attempt = retry ? cur + 1 : 0;
    vendorAttempts.current[key] = attempt;
    setVendorLogoBusy(key);
    try {
      await api.post(`/api/v1/brands/${brand.id}/vendors/fetch-logo`, {
        vendor_name: vendorName,
        attempt,
        variant,
      });
      await loadVendorLogos();
      toast.success(`${variant} logo updated — ${vendorName}`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "No logo found";
      toast.error(detail);
    } finally {
      setVendorLogoBusy(null);
    }
  };

  const uploadVendorLogo = async (vendorName: string, variant: VendorVariant, file: File) => {
    const key = _busyKey(vendorName, variant);
    setVendorLogoBusy(key);
    try {
      await api.uploadFile(
        `/api/v1/brands/${brand.id}/vendors/upload-logo?vendor_name=${encodeURIComponent(vendorName)}&variant=${variant}`,
        file
      );
      await loadVendorLogos();
      toast.success(`${variant} logo uploaded — ${vendorName}`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Upload failed";
      toast.error(detail);
    } finally {
      setVendorLogoBusy(null);
    }
  };

  const deleteVendorLogo = async (vendorName: string, variant: VendorVariant) => {
    const key = _busyKey(vendorName, variant);
    setVendorLogoBusy(key);
    try {
      await api.delete(
        `/api/v1/brands/${brand.id}/vendors/logo?vendor_name=${encodeURIComponent(vendorName)}&variant=${variant}`
      );
      await loadVendorLogos();
    } catch {
      toast.error("Failed to remove logo");
    } finally {
      setVendorLogoBusy(null);
    }
  };

  // ── Category logo handlers (mirror the vendor ones) ──────────────
  const fetchCategoryLogo = async (category: string, variant: VendorVariant, retry: boolean) => {
    const key = _busyKey(category, variant);
    const cur = categoryAttempts.current[key] ?? -1;
    const attempt = retry ? cur + 1 : 0;
    categoryAttempts.current[key] = attempt;
    setCategoryLogoBusy(key);
    try {
      await api.post(`/api/v1/brands/${brand.id}/categories/fetch-logo`, {
        category,
        attempt,
        variant,
      });
      await loadCategoryLogos();
      toast.success(`${variant} logo updated — ${category}`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "No logo found";
      toast.error(detail);
    } finally {
      setCategoryLogoBusy(null);
    }
  };

  const uploadCategoryLogo = async (category: string, variant: VendorVariant, file: File) => {
    const key = _busyKey(category, variant);
    setCategoryLogoBusy(key);
    try {
      await api.uploadFile(
        `/api/v1/brands/${brand.id}/categories/upload-logo?category=${encodeURIComponent(category)}&variant=${variant}`,
        file
      );
      await loadCategoryLogos();
      toast.success(`${variant} logo uploaded — ${category}`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Upload failed";
      toast.error(detail);
    } finally {
      setCategoryLogoBusy(null);
    }
  };

  const deleteCategoryLogo = async (category: string, variant: VendorVariant) => {
    const key = _busyKey(category, variant);
    setCategoryLogoBusy(key);
    try {
      await api.delete(
        `/api/v1/brands/${brand.id}/categories/logo?category=${encodeURIComponent(category)}&variant=${variant}`
      );
      await loadCategoryLogos();
    } catch {
      toast.error("Failed to remove logo");
    } finally {
      setCategoryLogoBusy(null);
    }
  };

  // Shared row renderer for both the vendor and category logo managers.
  const renderLogoRow = (
    name: string,
    lightUrl: string | null,
    darkUrl: string | null,
    isBusy: (variant: VendorVariant) => boolean,
    onFetch: (variant: VendorVariant, hasLogo: boolean) => void,
    onUpload: (variant: VendorVariant, file: File) => void,
    onDelete: (variant: VendorVariant) => void,
  ) => {
    const slots: { variant: VendorVariant; label: string; sub: string; url: string | null; darkBg: boolean }[] = [
      { variant: "light", label: "Light", sub: "light bg", url: lightUrl, darkBg: false },
      { variant: "dark", label: "Dark", sub: "dark bg", url: darkUrl, darkBg: true },
    ];
    return (
      <div key={name} className="py-3">
        <p className="truncate text-sm font-medium" title={name}>
          {name}
        </p>
        <div className="mt-2 grid grid-cols-2 gap-3">
          {slots.map(({ variant, label, sub, url, darkBg }) => {
            const busy = isBusy(variant);
            return (
              <div key={variant} className="rounded-md border p-2">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-xs font-medium">
                    {label} <span className="text-muted-foreground">· {sub}</span>
                  </span>
                  {url && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onDelete(variant)}
                      title={`Remove ${label} logo`}
                      className="text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <div
                  className={`flex h-14 items-center justify-center rounded-sm ring-1 ring-border ${darkBg ? "bg-neutral-800" : "bg-white/80"}`}
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  ) : url ? (
                    <img
                      src={`${fileUrl(url)}?v=${logoVersion}`}
                      alt={`${name} ${label}`}
                      className="h-12 max-w-[80%] object-contain p-0.5"
                      loading="lazy"
                    />
                  ) : (
                    <span className={`text-[10px] ${darkBg ? "text-neutral-400" : "text-muted-foreground"}`}>
                      No logo
                    </span>
                  )}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 flex-1 px-2 text-xs"
                    disabled={busy}
                    onClick={() => onFetch(variant, !!url)}
                    title={url ? "Search again for a different logo" : "Fetch from the web"}
                  >
                    {url ? <RotateCw className="h-3.5 w-3.5" /> : <Search className="mr-1 h-3.5 w-3.5" />}
                    {url ? "" : "Fetch"}
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 px-2" disabled={busy} asChild>
                    <label className="cursor-pointer">
                      <Upload className="h-3.5 w-3.5" />
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        className="hidden"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) onUpload(variant, file);
                          e.target.value = "";
                        }}
                      />
                    </label>
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const openSyncDialog = async () => {
    setSyncDialogOpen(true);
    setSelectedVendors(new Set());
    setSelectedCategories(new Set());
    setVendorSearch("");
    setCategorySearch("");
    setSyncOptionsLoading(true);
    try {
      const data = await api.get<SyncOptionsResponse>(
        `/api/v1/products/sync/${brand.id}/options`
      );
      setVendorOptions(
        (data.vendors || []).map((v) => ({ value: v.no, label: v.name || v.no }))
      );
      setCategoryOptions(
        (data.categories || []).map((c) => ({
          value: c.code,
          label: c.description ? `${c.code} — ${c.description}` : c.code,
        }))
      );
      // Pre-select the brand's previously saved filters so the user can see
      // and adjust them rather than starting from a blank list every time.
      setSelectedVendors(new Set(data.selected_vendor_nos || []));
      setSelectedCategories(new Set(data.selected_categories || []));
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to load sync options";
      toast.error(detail);
      setSyncDialogOpen(false);
    } finally {
      setSyncOptionsLoading(false);
    }
  };

  const filteredVendorOptions = useMemo(() => {
    const q = vendorSearch.trim().toLowerCase();
    if (!q) return vendorOptions;
    return vendorOptions.filter(
      (o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q)
    );
  }, [vendorOptions, vendorSearch]);

  const filteredCategoryOptions = useMemo(() => {
    const q = categorySearch.trim().toLowerCase();
    if (!q) return categoryOptions;
    return categoryOptions.filter(
      (o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q)
    );
  }, [categoryOptions, categorySearch]);

  const allVendorsSelected =
    filteredVendorOptions.length > 0 &&
    filteredVendorOptions.every((o) => selectedVendors.has(o.value));
  const allCategoriesSelected =
    filteredCategoryOptions.length > 0 &&
    filteredCategoryOptions.every((o) => selectedCategories.has(o.value));

  const toggleVendor = (value: string) => {
    setSelectedVendors((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value); else next.add(value);
      return next;
    });
  };
  const toggleCategory = (value: string) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value); else next.add(value);
      return next;
    });
  };

  const toggleAllVendors = () => {
    setSelectedVendors((prev) => {
      const next = new Set(prev);
      if (allVendorsSelected) {
        filteredVendorOptions.forEach((o) => next.delete(o.value));
      } else {
        filteredVendorOptions.forEach((o) => next.add(o.value));
      }
      return next;
    });
  };
  const toggleAllCategories = () => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (allCategoriesSelected) {
        filteredCategoryOptions.forEach((o) => next.delete(o.value));
      } else {
        filteredCategoryOptions.forEach((o) => next.add(o.value));
      }
      return next;
    });
  };

  const handleConfirmSync = async () => {
    setSyncDialogOpen(false);
    await onSyncProducts(
      selectedVendors.size > 0 ? Array.from(selectedVendors) : null,
      selectedCategories.size > 0 ? Array.from(selectedCategories) : null,
    );
  };

  if (!brand?.bc_company) {
    return (
      <div className="mt-6 space-y-6">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 space-y-4">
            <ShoppingBag className="h-12 w-12 text-muted-foreground/30" />
            <div className="text-center">
              <h3 className="text-lg font-medium">No Business Central Link</h3>
              <p className="text-sm text-muted-foreground mt-1">
                Link this brand to Business Central to sync products
              </p>
            </div>
            <Button variant="outline" onClick={() => onSetActiveTab("edit")}>
              Go to Edit Brand
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mt-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Products</h2>
          <p className="text-sm text-muted-foreground">
            {products.length} product{products.length !== 1 ? "s" : ""} synced from Business Central
            {products.length > 0 && products[0].bc_last_synced_at && (
              <> &middot; Last sync: {formatRelativeTime(products[0].bc_last_synced_at)}</>
            )}
          </p>
        </div>
        <Button
          size="sm"
          disabled={syncingProducts}
          onClick={openSyncDialog}
        >
          {syncingProducts ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 h-4 w-4" />
          )}
          {syncingProducts ? "Syncing..." : "Sync Products"}
        </Button>
      </div>

      {/* Filter bar */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <Label className="text-xs">Category</Label>
              <select
                value={productFilter.category}
                onChange={(e) => onSetProductFilter((prev) => ({ ...prev, category: e.target.value }))}
                className="flex h-9 w-48 rounded-md border border-input bg-background px-3 py-1 text-sm text-foreground"
              >
                <option value="">All Categories</option>
                {productCategories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Vendor</Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-9 w-56 justify-between font-normal"
                    disabled={productVendors.length === 0}
                  >
                    <span className="truncate">
                      {productFilter.vendors.length === 0
                        ? "All Vendors"
                        : productFilter.vendors.length === 1
                        ? productFilter.vendors[0]
                        : `${productFilter.vendors.length} selected`}
                    </span>
                    <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-64 max-h-80 overflow-y-auto">
                  <DropdownMenuLabel className="flex items-center justify-between">
                    <span>Vendors</span>
                    {productFilter.vendors.length > 0 && (
                      <button
                        type="button"
                        className="text-xs font-normal text-muted-foreground hover:text-foreground"
                        onClick={(e) => {
                          e.preventDefault();
                          onSetProductFilter((prev) => ({ ...prev, vendors: [] }));
                        }}
                      >
                        Clear
                      </button>
                    )}
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {productVendors.length === 0 ? (
                    <DropdownMenuItem disabled>No vendors</DropdownMenuItem>
                  ) : (
                    productVendors.map((vendor) => (
                      <DropdownMenuCheckboxItem
                        key={vendor}
                        checked={productFilter.vendors.includes(vendor)}
                        onSelect={(e) => e.preventDefault()}
                        onCheckedChange={(checked) =>
                          onSetProductFilter((prev) => ({
                            ...prev,
                            vendors: checked
                              ? [...prev.vendors, vendor]
                              : prev.vendors.filter((v) => v !== vendor),
                          }))
                        }
                      >
                        {vendor}
                      </DropdownMenuCheckboxItem>
                    ))
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Stock Level</Label>
              <select
                value={productFilter.stockLevel}
                onChange={(e) => onSetProductFilter((prev) => ({ ...prev, stockLevel: e.target.value }))}
                className="flex h-9 w-36 rounded-md border border-input bg-background px-3 py-1 text-sm text-foreground"
              >
                <option value="all">All</option>
                <option value="in-stock">In Stock</option>
                <option value="low">Low Stock</option>
                <option value="out">Out of Stock</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                checked={productFilter.newOnly}
                onCheckedChange={(checked) => onSetProductFilter((prev) => ({ ...prev, newOnly: checked }))}
              />
              <Label className="text-xs">New Arrivals</Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                checked={productFilter.expiringOnly}
                onCheckedChange={(checked) => onSetProductFilter((prev) => ({ ...prev, expiringOnly: checked }))}
              />
              <Label className="text-xs">Expiring Soon</Label>
            </div>
            <div className="ml-auto flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={fetchingImages !== null}
                onClick={onBatchFetchNoImage}
              >
                {fetchingImages === "batch" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ImageIcon className="mr-2 h-4 w-4" />}
                {fetchingImages === "batch" ? "Fetching..." : "Fetch images — No Image"}
              </Button>
              {selectedProductIds.size > 0 && (
                <Button
                  size="sm"
                  variant="default"
                  disabled={fetchingImages !== null}
                  onClick={onBatchFetchSelected}
                >
                  {fetchingImages === "batch-selected" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
                  Fetch images ({selectedProductIds.size})
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={openVendorLogos}>
                <Tag className="mr-2 h-4 w-4" />
                Fetch logo vendor
              </Button>
              <Button size="sm" variant="outline" onClick={() => onBulkProductActive(true)}>
                Include All
              </Button>
              <Button size="sm" variant="outline" onClick={() => onBulkProductActive(false)}>
                Exclude All
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Products table */}
      {loadingProducts ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-2 py-3 text-center w-8">
                      <input type="checkbox" className="rounded-sm border-muted-foreground/40"
                        checked={selectedProductIds.size > 0 && selectedProductIds.size === filteredProducts.length}
                        onChange={(e) => {
                          if (e.target.checked) {
                            onSetSelectedProductIds(new Set(filteredProducts.map((p) => p.id)));
                          } else {
                            onSetSelectedProductIds(new Set());
                          }
                        }}
                      />
                    </th>
                    <th className="px-4 py-3 text-left font-medium">Name</th>
                    <th className="px-4 py-3 text-left font-medium">Category</th>
                    <th className="px-4 py-3 text-right font-medium">Price</th>
                    <th className="px-4 py-3 text-right font-medium">Stock</th>
                    <th className="px-4 py-3 text-center font-medium">Images</th>
                    <th className="px-4 py-3 text-center font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredProducts.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                        {products.length === 0
                          ? "No products synced yet. Click Sync Products to get started."
                          : "No products match the current filters."}
                      </td>
                    </tr>
                  ) : (
                    pagedProducts.map((product) => (
                      <React.Fragment key={product.id}>
                        <tr className="border-b hover:bg-muted/30 [&>td]:align-middle">
                          <td className="px-2 py-3 text-center w-8" onClick={(e) => e.stopPropagation()}>
                            <input type="checkbox" className="rounded-sm border-muted-foreground/40"
                              checked={selectedProductIds.has(product.id)}
                              onChange={() => onToggleProductSelection(product.id)}
                            />
                          </td>
                          <td className="px-4 py-3">
                            <div>
                              <div className="flex items-center gap-1.5">
                                <p className="font-medium">{product.name}</p>
                                {product.is_new && (
                                  <Badge variant="secondary" className="text-[10px]">New</Badge>
                                )}
                                {product.is_expiring_soon && (
                                  <Badge variant="destructive" className="text-[10px]">Expiring</Badge>
                                )}
                              </div>
                              {product.sku && (
                                <p className="text-xs text-muted-foreground">SKU: {product.sku}</p>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <span className="text-muted-foreground">{product.category || "\u2014"}</span>
                          </td>
                          <td className="px-4 py-3 text-right">
                            {product.unit_price != null
                              ? `${product.currency || ""}${product.unit_price.toFixed(2)}`
                              : "\u2014"}
                          </td>
                          <td className="px-4 py-3 align-middle text-right">
                            <button
                              type="button"
                              className={`inline-flex items-center justify-end gap-1 rounded-sm px-2 py-0.5 text-sm tabular-nums transition-colors hover:bg-muted ${
                                (product.remaining_qty ?? 0) <= 0
                                  ? "text-red-500 dark:text-red-400 font-medium"
                                  : (product.remaining_qty ?? 0) <= 10
                                  ? "text-yellow-600 dark:text-yellow-400 font-medium"
                                  : ""
                              }`}
                              onClick={() => onSetExpandedProductId(
                                expandedProductId === product.id ? null : product.id
                              )}
                              title="Click to see lot/expiry breakdown"
                            >
                              {product.remaining_qty ?? 0}
                              <svg className={`h-3 w-3 shrink-0 transition-transform ${expandedProductId === product.id ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M3 5l3 3 3-3" />
                              </svg>
                            </button>
                          </td>
                          <td className="px-4 py-3 text-center">
                            {product.primary_image_url ? (
                              <button
                                className="inline-flex items-center justify-center gap-1 cursor-pointer hover:opacity-80 transition-opacity"
                                onClick={(e) => { e.stopPropagation(); onOpenGallery(product); }}
                              >
                                <img src={fileUrl(product.primary_image_url)} alt="" className="h-8 w-8 rounded-sm object-cover ring-1 ring-border" loading="lazy" />
                                <span className="text-[10px] text-muted-foreground">
                                  {Array.isArray(product.image_urls) ? product.image_urls.length : 0}
                                </span>
                              </button>
                            ) : (
                              <div className="inline-flex items-center justify-center gap-1">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 text-xs"
                                  disabled={fetchingImages === product.id}
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    // This triggers from parent through the fetchingImages state
                                  }}
                                >
                                  {fetchingImages === product.id ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    <Search className="h-3 w-3" />
                                  )}
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 text-xs"
                                  onClick={(e) => { e.stopPropagation(); onOpenGallery(product); }}
                                >
                                  <Upload className="h-3 w-3" />
                                </Button>
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <div className="flex items-center justify-center gap-2">
                              <Switch
                                checked={product.is_active}
                                disabled={togglingProduct === product.id}
                                onCheckedChange={(checked) =>
                                  onToggleProductActive(product.id, checked)
                                }
                              />
                              <span className="text-xs text-muted-foreground w-14">
                                {product.is_active ? "Include" : "Exclude"}
                              </span>
                            </div>
                          </td>
                        </tr>
                        {expandedProductId === product.id && (
                          <tr className="bg-muted/10 border-b">
                            <td colSpan={3} className="px-4 py-2">
                              <p className="text-xs font-medium text-muted-foreground">Stock Breakdown</p>
                              {product.bc_location && (
                                <p className="text-[11px] text-muted-foreground/70">Location: {product.bc_location}</p>
                              )}
                            </td>
                            <td className="px-4 py-2 text-xs text-right font-medium text-muted-foreground">Lot No.</td>
                            <td className="px-4 py-2 text-xs text-right font-medium text-muted-foreground">Qty / Expiry</td>
                            <td colSpan={2} />
                          </tr>
                        )}
                        {expandedProductId === product.id && (
                          product.lot_no ? (
                            <tr className="bg-muted/10 border-b">
                              <td colSpan={3} />
                              <td className="px-4 py-1.5 text-xs text-right font-mono">{product.lot_no}</td>
                              <td className="px-4 py-1.5 text-xs text-right">
                                {product.remaining_qty ?? 0}
                                {product.expiry_date && (
                                  <span className={`ml-2 ${
                                    new Date(product.expiry_date) < new Date(Date.now() + 30 * 86400000)
                                      ? "text-red-500 font-medium" : "text-muted-foreground"
                                  }`}>
                                    exp. {product.expiry_date}
                                  </span>
                                )}
                              </td>
                              <td colSpan={2} />
                            </tr>
                          ) : (
                            <tr className="bg-muted/10 border-b">
                              <td colSpan={3} />
                              <td colSpan={2} className="px-4 py-1.5 text-xs text-muted-foreground italic text-right">
                                No lot tracking — total: {product.remaining_qty ?? 0}
                              </td>
                              <td colSpan={2} />
                            </tr>
                          )
                        )}
                      </React.Fragment>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {filteredProducts.length > PAGE_SIZE && (
              <div className="flex items-center justify-between border-t px-4 py-3 text-sm">
                <span className="text-muted-foreground">
                  Showing {(page - 1) * PAGE_SIZE + 1}–
                  {Math.min(page * PAGE_SIZE, filteredProducts.length)} of {filteredProducts.length}
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <span className="px-2">Page {page} / {totalPages}</span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Sync Filter Dialog */}
      <Dialog open={syncDialogOpen} onOpenChange={(open) => { if (!open) setSyncDialogOpen(false); }}>
        <DialogContent className="max-w-3xl">
          <DialogTitle className="flex items-center gap-2">
            <RefreshCw className="h-5 w-5" />
            Sync Products from Business Central
          </DialogTitle>
          <DialogDescription>
            Select vendors and categories to sync. Leave a list empty to include all of that type.
          </DialogDescription>

          {syncOptionsLoading ? (
            <div className="space-y-2 py-6">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Vendors */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium">
                    Vendors ({selectedVendors.size}/{vendorOptions.length})
                  </Label>
                  <button
                    type="button"
                    className="text-xs text-primary hover:underline"
                    onClick={toggleAllVendors}
                  >
                    {allVendorsSelected ? "Clear All" : "Select All"}
                  </button>
                </div>
                <input
                  type="text"
                  value={vendorSearch}
                  onChange={(e) => setVendorSearch(e.target.value)}
                  placeholder="Search vendors..."
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                />
                <div className="h-72 overflow-y-auto rounded-md border bg-background p-2">
                  {filteredVendorOptions.length === 0 ? (
                    <p className="text-xs text-muted-foreground p-2">No vendors</p>
                  ) : (
                    filteredVendorOptions.map((opt) => (
                      <label
                        key={opt.value}
                        className="flex items-start gap-2 px-2 py-1.5 text-sm hover:bg-muted/50 rounded-sm cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5 rounded-sm"
                          checked={selectedVendors.has(opt.value)}
                          onChange={() => toggleVendor(opt.value)}
                        />
                        <span className="flex-1 truncate" title={opt.label}>{opt.label}</span>
                      </label>
                    ))
                  )}
                </div>
              </div>

              {/* Categories */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium">
                    Categories ({selectedCategories.size}/{categoryOptions.length})
                  </Label>
                  <button
                    type="button"
                    className="text-xs text-primary hover:underline"
                    onClick={toggleAllCategories}
                  >
                    {allCategoriesSelected ? "Clear All" : "Select All"}
                  </button>
                </div>
                <input
                  type="text"
                  value={categorySearch}
                  onChange={(e) => setCategorySearch(e.target.value)}
                  placeholder="Search categories..."
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                />
                <div className="h-72 overflow-y-auto rounded-md border bg-background p-2">
                  {filteredCategoryOptions.length === 0 ? (
                    <p className="text-xs text-muted-foreground p-2">No categories</p>
                  ) : (
                    filteredCategoryOptions.map((opt) => (
                      <label
                        key={opt.value}
                        className="flex items-start gap-2 px-2 py-1.5 text-sm hover:bg-muted/50 rounded-sm cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5 rounded-sm"
                          checked={selectedCategories.has(opt.value)}
                          onChange={() => toggleCategory(opt.value)}
                        />
                        <span className="flex-1 truncate" title={opt.label}>{opt.label}</span>
                      </label>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={() => setSyncDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={syncOptionsLoading}
              onClick={handleConfirmSync}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              {selectedVendors.size === 0 && selectedCategories.size === 0
                ? "Sync All"
                : "Sync Selected"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Product Image Gallery Dialog */}
      <Dialog open={!!galleryProduct} onOpenChange={(open) => { if (!open) onSetGalleryProduct(null); }}>
        <DialogContent className="max-w-2xl">
          <DialogTitle className="flex items-center gap-2">
            <ImageIcon className="h-5 w-5" />
            {galleryProduct?.name} — Image Gallery
          </DialogTitle>
          <DialogDescription>
            Manage product images. Click an image to set it as primary. Use the web search to find real product photos.
          </DialogDescription>

          {galleryLoading ? (
            <div className="grid grid-cols-3 gap-3">
              <Skeleton className="aspect-square rounded-lg" />
              <Skeleton className="aspect-square rounded-lg" />
              <Skeleton className="aspect-square rounded-lg" />
            </div>
          ) : galleryImages.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <ImageIcon className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>No images yet</p>
              <p className="text-xs mt-1">Use web search or upload to add product images</p>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              {galleryImages.map((img, i) => (
                <div key={i} className="relative group aspect-square rounded-lg overflow-hidden border bg-muted">
                  <img
                    src={fileUrl(typeof img === "string" ? img : img.url)}
                    alt=""
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                  {galleryProduct?.primary_image_url === (typeof img === "string" ? img : img.url) && (
                    <Badge className="absolute top-1 left-1 text-[10px] h-4 bg-primary">Primary</Badge>
                  )}
                  {typeof img !== "string" && img.source && (
                    <Badge variant="secondary" className="absolute bottom-1 left-1 text-[10px] h-4">
                      {img.source === "web_search" ? "Web" : img.source === "upload" ? "Upload" : img.source}
                    </Badge>
                  )}
                  <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                    <Button size="sm" variant="secondary" className="h-7 text-xs" onClick={() => onSetPrimaryImage(i)}>
                      <CheckCircle2 className="h-3 w-3 mr-1" /> Primary
                    </Button>
                    <Button size="sm" variant="destructive" className="h-7 text-xs" onClick={() => onDeleteGalleryImage(i)}>
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <Button
              size="sm"
              variant="outline"
              disabled={fetchingImages === galleryProduct?.id}
              onClick={async () => {
                if (galleryProduct) await onSearchWebImages(galleryProduct);
              }}
            >
              {fetchingImages === galleryProduct?.id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
              Fetch image
            </Button>
            <Button size="sm" variant="outline" asChild>
              <label className="cursor-pointer">
                <Upload className="mr-2 h-4 w-4" />
                Upload
                <input
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) onUploadProductImage(file);
                    e.target.value = "";
                  }}
                />
              </label>
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Vendor logo modal — one logo per manufacturer, reused for all its
          products at generation time. */}
      <Dialog open={vendorLogoOpen} onOpenChange={setVendorLogoOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogTitle className="flex items-center gap-2">
            <Tag className="h-4 w-4" /> Vendor &amp; category logos
          </DialogTitle>
          <DialogDescription>
            Each vendor (manufacturer) <i>or</i> category can have a <b>Light</b>{" "}
            variant (light/white backgrounds) and a <b>Dark</b> variant (dark
            backgrounds). The renderer auto-picks the right one per post. A product
            with no vendor logo falls back to its <b>category</b> logo — useful for
            items whose vendor is blank or blocked in BC.
          </DialogDescription>

          {/* Vendors */}
          <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Vendors
          </p>
          {vendorLogosLoading ? (
            <div className="space-y-2 py-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : vendorLogos.length === 0 ? (
            <p className="py-3 text-center text-sm text-muted-foreground">
              No vendors yet — sync products first.
            </p>
          ) : (
            <div className="divide-y">
              {vendorLogos.map((v) =>
                renderLogoRow(
                  v.vendor_name,
                  v.light_url,
                  v.dark_url,
                  (variant) => vendorLogoBusy === _busyKey(v.vendor_name, variant),
                  (variant, hasLogo) => fetchVendorLogo(v.vendor_name, variant, hasLogo),
                  (variant, file) => uploadVendorLogo(v.vendor_name, variant, file),
                  (variant) => deleteVendorLogo(v.vendor_name, variant),
                )
              )}
            </div>
          )}

          {/* Categories — fallback logo for products whose vendor has none */}
          <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Categories
          </p>
          {categoryLogosLoading ? (
            <div className="space-y-2 py-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : categoryLogos.length === 0 ? (
            <p className="py-3 text-center text-sm text-muted-foreground">
              No categories yet — sync products first.
            </p>
          ) : (
            <div className="divide-y">
              {categoryLogos.map((c) =>
                renderLogoRow(
                  c.category,
                  c.light_url,
                  c.dark_url,
                  (variant) => categoryLogoBusy === _busyKey(c.category, variant),
                  (variant, hasLogo) => fetchCategoryLogo(c.category, variant, hasLogo),
                  (variant, file) => uploadCategoryLogo(c.category, variant, file),
                  (variant) => deleteCategoryLogo(c.category, variant),
                )
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
