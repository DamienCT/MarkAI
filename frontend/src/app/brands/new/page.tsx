"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BrandForm } from "@/components/brand/BrandForm";
import { api } from "@/lib/api";
import { useRequireRole } from "@/lib/hooks";
import type { Brand } from "@/types";

export default function NewBrandPage() {
  useRequireRole("editor"); // redirects unauthorized users as a side effect
  const router = useRouter();
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (data: Partial<Brand>) => {
    if (!data.name?.trim()) {
      toast.error("Brand name is required");
      return;
    }
    setSaving(true);
    try {
      const brand = await api.post<Brand>("/api/v1/brands", data);
      toast.success("Brand created successfully");
      router.push(`/brands/${brand.id}`);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to create brand";
      toast.error(detail);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => router.push("/brands")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-3xl font-bold">Create Brand</h1>
          <p className="text-muted-foreground">Set up a new brand profile</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Brand Details</CardTitle>
          <CardDescription>Fill in the brand information below</CardDescription>
        </CardHeader>
        <CardContent>
          <BrandForm onSubmit={handleSubmit} loading={saving} />
        </CardContent>
      </Card>
    </div>
  );
}
