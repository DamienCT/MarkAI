"use client";

import React from "react";
import { Upload, X, ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { apiUrl } from "@/lib/api";

interface LogoInfo {
  url: string;
  label: string;
  filename?: string;
}

const LOGO_LABELS = [
  { value: "primary", label: "Primary Logo", desc: "Main brand logo used across content" },
  { value: "icon", label: "Icon / Favicon", desc: "Small square icon for profile pictures" },
  { value: "watermark", label: "Watermark", desc: "Transparent overlay for images/videos" },
  { value: "dark", label: "Dark Variant", desc: "Logo variant for dark backgrounds" },
  { value: "light", label: "Light Variant", desc: "Logo variant for light backgrounds" },
];

export interface LogosTabProps {
  logos: Record<string, LogoInfo> | undefined;
  uploadingLogo: boolean;
  selectedLogoLabel: string;
  onSetSelectedLogoLabel: (label: string) => void;
  onLogoUpload: (e: React.ChangeEvent<HTMLInputElement>) => Promise<void>;
  onDeleteLogo: (label: string) => Promise<void>;
}

export function LogosTab({
  logos,
  uploadingLogo,
  selectedLogoLabel,
  onSetSelectedLogoLabel,
  onLogoUpload,
  onDeleteLogo,
}: LogosTabProps) {
  return (
    <div className="mt-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Brand Logos</CardTitle>
          <CardDescription>
            Upload multiple logo variants for use across all channels and content
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Current logos */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {LOGO_LABELS.map(({ value, label, desc }) => {
              const logoInfo = logos?.[value];
              return (
                <div key={value} className="rounded-lg border p-4 space-y-3">
                  <div>
                    <h4 className="text-sm font-medium">{label}</h4>
                    <p className="text-xs text-muted-foreground">{desc}</p>
                  </div>
                  {logoInfo ? (
                    <div className="relative group">
                      <img
                        src={apiUrl(logoInfo.url)}
                        alt={label}
                        className="h-24 w-full object-contain rounded-md border bg-muted/20"
                      />
                      <Button
                        variant="destructive"
                        size="sm"
                        className="absolute top-1 right-1 h-6 w-6 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={() => onDeleteLogo(value)}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                      {logoInfo.filename && (
                        <p className="text-xs text-muted-foreground mt-1 truncate">{logoInfo.filename}</p>
                      )}
                    </div>
                  ) : (
                    <div className="h-24 rounded-md border border-dashed flex items-center justify-center bg-muted/10">
                      <ImageIcon className="h-8 w-8 text-muted-foreground/30" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Upload */}
          <div className="rounded-lg border p-4 space-y-3">
            <h4 className="text-sm font-medium">Upload Logo</h4>
            <div className="flex items-end gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Logo Type</Label>
                <select
                  value={selectedLogoLabel}
                  onChange={(e) => onSetSelectedLogoLabel(e.target.value)}
                  className="flex h-9 w-48 rounded-md border border-input bg-background px-3 py-1 text-sm text-foreground"
                >
                  {LOGO_LABELS.map(({ value, label }) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label
                  htmlFor="logo-upload"
                  className="inline-flex items-center gap-2 cursor-pointer h-9 px-4 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90"
                >
                  <Upload className="h-4 w-4" />
                  {uploadingLogo ? "Uploading..." : "Choose File"}
                </Label>
                <input
                  id="logo-upload"
                  type="file"
                  accept="image/png,image/jpeg,image/svg+xml,image/webp"
                  onChange={onLogoUpload}
                  disabled={uploadingLogo}
                  className="sr-only"
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              PNG, JPEG, SVG, or WebP. Max 5MB. Logos are attached to all published content.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
