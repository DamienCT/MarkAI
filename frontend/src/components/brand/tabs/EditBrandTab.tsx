"use client";

import React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BrandForm } from "@/components/brand/BrandForm";
import type { Brand } from "@/types";

export interface EditBrandTabProps {
  brand: Brand;
  saving: boolean;
  onSave: (data: Partial<Brand>) => Promise<void>;
}

export function EditBrandTab({ brand, saving, onSave }: EditBrandTabProps) {
  return (
    <div className="mt-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Edit Brand</CardTitle>
          <CardDescription>Update brand details and configuration</CardDescription>
        </CardHeader>
        <CardContent>
          <BrandForm brand={brand} onSubmit={onSave} loading={saving} />
        </CardContent>
      </Card>
    </div>
  );
}
