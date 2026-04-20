"use client";

import React, { useEffect, useState } from "react";
import { Building2 } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { getStoredBrandValue, setStoredBrandValue } from "@/lib/brand-selection";
import type { Brand } from "@/types";

export function BrandSwitcher() {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [selectedBrand, setSelectedBrand] = useState<string>("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Hydrate after mount to avoid SSR/client mismatch — localStorage is client-only.
    setSelectedBrand(getStoredBrandValue());
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function fetchBrands() {
      try {
        const data = await api.get<Brand[]>("/api/v1/brands", undefined, { signal: controller.signal });
        setBrands(data);
      } catch {
        // Silently fail on initial load — API may not be ready yet
      } finally {
        setLoading(false);
      }
    }
    fetchBrands();
    return () => controller.abort();
  }, []);

  const handleChange = (value: string) => {
    setSelectedBrand(value);
    setStoredBrandValue(value);
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("brand-changed", { detail: { brandId: value === "all" ? null : value } })
      );
    }
  };

  if (loading) {
    return (
      <div className="h-10 rounded-md border bg-background animate-pulse" />
    );
  }

  return (
    <Select value={selectedBrand} onValueChange={handleChange}>
      <SelectTrigger className="w-full">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4" />
          <SelectValue placeholder="All Brands" />
        </div>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">All Brands</SelectItem>
        {brands.map((brand) => (
          <SelectItem key={brand.id} value={brand.id}>
            {brand.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
