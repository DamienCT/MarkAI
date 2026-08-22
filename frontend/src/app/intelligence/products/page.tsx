"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isAuthError } from "@/lib/api";
import { getStoredBrandId } from "@/lib/brand-selection";
import { formatDate } from "@/lib/utils";
import type { Product } from "@/types";

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchProducts(brandId?: string | null) {
      setLoading(true);
      try {
        const params: Record<string, string | number> = { limit: 100 };
        if (brandId) params.brand_id = brandId;
        const data = await api.get<Product[]>("/api/v1/products", params);
        setProducts(data);
      } catch (err) {
        // Session expiry: the sign-in redirect is already underway.
        if (!isAuthError(err)) toast.error("Failed to load products");
      } finally {
        setLoading(false);
      }
    }
    fetchProducts(getStoredBrandId());

    // Follow the global sidebar brand selection.
    const handler = (e: Event) => {
      const brandId = (e as CustomEvent).detail?.brandId;
      fetchProducts(brandId);
    };
    window.addEventListener("brand-changed", handler);
    return () => window.removeEventListener("brand-changed", handler);
  }, []);

  const newArrivals = products.filter((p) => p.is_new);
  const expiring = products.filter((p) => p.is_expiring_soon);
  const activeCount = products.filter((p) => p.is_active).length;
  const withImages = products.filter((p) => p.primary_image_url).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Product Intelligence</h1>
        <p className="text-muted-foreground">BC product catalog sync and intelligence</p>
      </div>

      {loading ? (
        <Skeleton className="h-96" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Total Products</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold">{products.length}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Active</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold">{activeCount}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>New Arrivals</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold">{newArrivals.length}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>With Images</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold">{withImages}</p>
              </CardContent>
            </Card>
          </div>

          {expiring.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Expiring Soon</CardTitle>
                <CardDescription>Products nearing end-of-life</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Product</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead>Price</TableHead>
                      <TableHead>Qty</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {expiring.map((product) => (
                      <TableRow key={product.id}>
                        <TableCell className="font-medium">{product.name}</TableCell>
                        <TableCell>{product.category || "--"}</TableCell>
                        <TableCell>
                          {product.currency || ""} {product.unit_price?.toFixed(2) || "--"}
                        </TableCell>
                        <TableCell>{product.remaining_qty ?? "--"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">All Products</CardTitle>
              <CardDescription>Synced product catalog</CardDescription>
            </CardHeader>
            <CardContent>
              {products.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">No products synced yet</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Product</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead>Price</TableHead>
                      <TableHead>Stock</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Synced</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {products.map((product) => (
                      <TableRow key={product.id}>
                        <TableCell className="font-medium">{product.name}</TableCell>
                        <TableCell>{product.category || "--"}</TableCell>
                        <TableCell>
                          {product.currency || ""} {product.unit_price?.toFixed(2) || "--"}
                        </TableCell>
                        <TableCell>{product.remaining_qty ?? "--"}</TableCell>
                        <TableCell>
                          <Badge variant={product.is_active ? "default" : "outline"}>
                            {product.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {product.bc_last_synced_at ? formatDate(product.bc_last_synced_at) : "--"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
