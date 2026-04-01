"use client";

import React, { useState } from "react";
import { X, ZoomIn } from "lucide-react";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

interface AssetPreviewProps {
  url: string;
  alt?: string;
}

export function AssetPreview({ url, alt = "Asset" }: AssetPreviewProps) {
  const isVideo = /\.(mp4|webm|mov)$/i.test(url);

  return (
    <Dialog>
      <DialogTrigger asChild>
        <div className="relative group cursor-pointer rounded-lg overflow-hidden border bg-muted aspect-square">
          {isVideo ? (
            <video src={url} className="h-full w-full object-cover" muted />
          ) : (
            <img src={url} alt={alt} className="h-full w-full object-cover" loading="lazy" />
          )}
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
            <ZoomIn className="h-6 w-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </div>
      </DialogTrigger>
      <DialogContent className="max-w-3xl p-0 overflow-hidden">
        <DialogTitle className="sr-only">Asset preview</DialogTitle>
        {isVideo ? (
          <video src={url} controls className="w-full" />
        ) : (
          <img src={url} alt={alt} className="w-full" loading="lazy" />
        )}
      </DialogContent>
    </Dialog>
  );
}
