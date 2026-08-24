"use client";

import React from "react";
import { Smartphone } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { MediaImage } from "@/components/ui/media-image";

interface PlatformMockupsProps {
  mockupUrls: Record<string, string>;
  imageBaseUrl?: string;
}

const PLATFORM_LABELS: Record<string, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  x: "X (Twitter)",
};

/**
 * Shows social platform mockup previews — how the post would look
 * in each platform's mobile feed. Used in the approval flow.
 */
export function PlatformMockups({ mockupUrls, imageBaseUrl = "" }: PlatformMockupsProps) {
  const platforms = Object.keys(mockupUrls).filter((p) => mockupUrls[p]);

  if (platforms.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Smartphone className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-lg">Platform Previews</CardTitle>
        </div>
        <p className="text-sm text-muted-foreground">
          See how this post will appear on each platform before approving.
        </p>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue={platforms[0]}>
          <TabsList className="grid w-full" style={{ gridTemplateColumns: `repeat(${platforms.length}, 1fr)` }}>
            {platforms.map((p) => (
              <TabsTrigger key={p} value={p} className="text-xs">
                {PLATFORM_LABELS[p] || p}
              </TabsTrigger>
            ))}
          </TabsList>

          {platforms.map((p) => {
            const fullUrl = mockupUrls[p].startsWith("http")
              ? mockupUrls[p]
              : `${imageBaseUrl}/${mockupUrls[p]}`;
            // Thumbnail: 400px wide, JPEG quality 70 for fast preview
            const thumbUrl = fullUrl.includes("?")
              ? `${fullUrl}&w=400&q=70`
              : `${fullUrl}?w=400&q=70`;

            return (
              <TabsContent key={p} value={p} className="mt-4">
                <Dialog>
                  <DialogTrigger asChild>
                    <div className="cursor-pointer mx-auto max-w-[280px] rounded-2xl border-2 border-muted shadow-lg overflow-hidden hover:shadow-xl transition-shadow bg-black">
                      <MediaImage
                        src={thumbUrl}
                        alt={`${PLATFORM_LABELS[p] || p} preview`}
                        className="w-full h-auto"
                        loading="lazy"
                      />
                    </div>
                  </DialogTrigger>
                  <DialogContent className="max-w-md p-2 overflow-hidden bg-black">
                    <MediaImage
                      src={fullUrl}
                      alt={`${PLATFORM_LABELS[p] || p} preview`}
                      className="w-full h-auto rounded-lg"
                      loading="lazy"
                    />
                  </DialogContent>
                </Dialog>
                <p className="text-center text-xs text-muted-foreground mt-3">
                  Click to enlarge — {PLATFORM_LABELS[p] || p} mobile feed preview
                </p>
              </TabsContent>
            );
          })}
        </Tabs>
      </CardContent>
    </Card>
  );
}
