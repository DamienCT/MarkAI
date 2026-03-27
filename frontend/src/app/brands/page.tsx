"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BrandCard } from "@/components/brand/BrandCard";
import { api } from "@/lib/api";
import type { Brand } from "@/types";

export default function BrandsPage() {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchBrands() {
      try {
        const data = await api.get<Brand[]>("/api/v1/brands");
        setBrands(data);
      } catch {
        setError("Failed to load brands");
      } finally {
        setLoading(false);
      }
    }
    fetchBrands();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Brands</h1>
          <p className="text-muted-foreground">Manage your brand profiles and social accounts</p>
        </div>
        <Link href="/brands/new">
          <Button>
            <Plus className="mr-2 h-4 w-4" />
            New Brand
          </Button>
        </Link>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-48 rounded-lg" />
          ))}
        </div>
      ) : error ? (
        <div className="text-center py-12">
          <p className="text-muted-foreground">{error}</p>
          <Button
            variant="outline"
            className="mt-4"
            onClick={() => {
              setError(null);
              setLoading(true);
              api.get<Brand[]>("/api/v1/brands").then(setBrands).catch(() => setError("Failed to load brands")).finally(() => setLoading(false));
            }}
          >
            Retry
          </Button>
        </div>
      ) : brands.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-lg text-muted-foreground">No brands yet</p>
          <p className="text-sm text-muted-foreground mt-1">Create your first brand to get started.</p>
          <Link href="/brands/new">
            <Button className="mt-4">
              <Plus className="mr-2 h-4 w-4" />
              Create Brand
            </Button>
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {brands.map((brand) => (
            <BrandCard key={brand.id} brand={brand} />
          ))}
        </div>
      )}
    </div>
  );
}
