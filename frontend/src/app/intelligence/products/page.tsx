"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { statusColor, formatDate } from "@/lib/utils";
import type { Product } from "@/types";

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchProducts() {
      try {
        const data = await api.get<Product[]>("/api/v1/products", { limit: 100 });
        setProducts(data);
      } catch {
        // Handle error
      } finally {
        setLoading(false);
      }
    }
    fetchProducts();
  }, []);

  const newArrivals = products.filter((p) => p.status === "new_arrival");
  const expiring = products.filter((p) => p.status === "expiring");
  const activeCount = products.filter((p) => p.status === "active").length;
  const withImages = products.filter((p) => p.image_urls.length > 0).length;

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
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {expiring.map((product) => (
                      <TableRow key={product.id}>
                        <TableCell className="font-medium">{product.name}</TableCell>
                        <TableCell>{product.category}</TableCell>
                        <TableCell>
                          {product.currency} {product.price.toFixed(2)}
                        </TableCell>
                        <TableCell>
                          <Badge className={statusColor(product.status)}>{product.status}</Badge>
                        </TableCell>
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
                      <TableHead>Images</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Synced</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {products.map((product) => (
                      <TableRow key={product.id}>
                        <TableCell className="font-medium">{product.name}</TableCell>
                        <TableCell>{product.category}</TableCell>
                        <TableCell>
                          {product.currency} {product.price.toFixed(2)}
                        </TableCell>
                        <TableCell>{product.image_urls.length}</TableCell>
                        <TableCell>
                          <Badge className={statusColor(product.status)} variant="outline">
                            {product.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {formatDate(product.synced_at)}
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
