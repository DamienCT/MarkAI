"use client";

import React from "react";
import {
  ShoppingBag, RefreshCw, Loader2, Search, Upload, ImageIcon,
  CheckCircle2, Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { formatRelativeTime } from "@/lib/utils";
import type { Brand, Product } from "@/types";

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
  };
  togglingProduct: string | null;
  expandedProductId: string | null;
  fetchingImages: string | null;
  galleryProduct: Product | null;
  galleryImages: { url: string; object_name?: string; source?: string }[];
  galleryLoading: boolean;
  selectedProductIds: Set<string>;
  productCategories: string[];
  onSetActiveTab: (tab: string) => void;
  onSyncProducts: () => Promise<void>;
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
  getFilteredProducts,
}: ProductsTabProps) {
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
          onClick={onSyncProducts}
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
                {fetchingImages === "batch" ? "Fetching..." : "Fetch Images (No Image)"}
              </Button>
              {selectedProductIds.size > 0 && (
                <Button
                  size="sm"
                  variant="default"
                  disabled={fetchingImages !== null}
                  onClick={onBatchFetchSelected}
                >
                  {fetchingImages === "batch-selected" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
                  Fetch Images ({selectedProductIds.size} selected)
                </Button>
              )}
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
                        checked={selectedProductIds.size > 0 && selectedProductIds.size === getFilteredProducts().length}
                        onChange={(e) => {
                          if (e.target.checked) {
                            onSetSelectedProductIds(new Set(getFilteredProducts().map((p) => p.id)));
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
                  {getFilteredProducts().length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                        {products.length === 0
                          ? "No products synced yet. Click Sync Products to get started."
                          : "No products match the current filters."}
                      </td>
                    </tr>
                  ) : (
                    getFilteredProducts().map((product) => (
                      <React.Fragment key={product.id}>
                        <tr className="border-b hover:bg-muted/30">
                          <td className="px-2 py-3 text-center w-8" onClick={(e) => e.stopPropagation()}>
                            <input type="checkbox" className="rounded-sm border-muted-foreground/40"
                              checked={selectedProductIds.has(product.id)}
                              onChange={() => onToggleProductSelection(product.id)}
                            />
                          </td>
                          <td className="px-4 py-3">
                            <div>
                              <p className="font-medium">{product.name}</p>
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
                          <td className="px-4 py-3 text-right">
                            <button
                              type="button"
                              className={`inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-sm transition-colors hover:bg-muted ${
                                (product.remaining_qty ?? 0) <= 0
                                  ? "text-red-500 font-medium"
                                  : (product.remaining_qty ?? 0) <= 10
                                  ? "text-yellow-600 font-medium"
                                  : ""
                              }`}
                              onClick={() => onSetExpandedProductId(
                                expandedProductId === product.id ? null : product.id
                              )}
                              title="Click to see lot/expiry breakdown"
                            >
                              {product.remaining_qty ?? 0}
                              <svg className={`h-3 w-3 transition-transform ${expandedProductId === product.id ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M3 5l3 3 3-3" />
                              </svg>
                            </button>
                            {product.is_new && (
                              <Badge variant="secondary" className="ml-1 text-[10px]">New</Badge>
                            )}
                            {product.is_expiring_soon && (
                              <Badge variant="destructive" className="ml-1 text-[10px]">Expiring</Badge>
                            )}
                          </td>
                          <td className="px-4 py-3 text-center">
                            {product.primary_image_url ? (
                              <button
                                className="flex items-center justify-center gap-1 cursor-pointer hover:opacity-80 transition-opacity"
                                onClick={(e) => { e.stopPropagation(); onOpenGallery(product); }}
                              >
                                <img src={product.primary_image_url} alt="" className="h-8 w-8 rounded-sm object-cover ring-1 ring-border" loading="lazy" />
                                <span className="text-[10px] text-muted-foreground">
                                  {Array.isArray(product.image_urls) ? product.image_urls.length : 0}
                                </span>
                              </button>
                            ) : (
                              <div className="flex items-center justify-center gap-1">
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
          </CardContent>
        </Card>
      )}

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
                    src={typeof img === "string" ? img : img.url}
                    alt=""
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                  {galleryProduct?.primary_image_url === (typeof img === "string" ? img : img.url) && (
                    <Badge className="absolute top-1 left-1 text-[9px] h-4 bg-primary">Primary</Badge>
                  )}
                  {typeof img !== "string" && img.source && (
                    <Badge variant="secondary" className="absolute bottom-1 left-1 text-[9px] h-4">
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
                if (galleryProduct) onOpenGallery(galleryProduct);
              }}
            >
              {fetchingImages === galleryProduct?.id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
              Search Web
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
    </div>
  );
}
