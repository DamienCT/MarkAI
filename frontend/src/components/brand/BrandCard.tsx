"use client";

import React from "react";
import Link from "next/link";
import { Building2, MapPin, Instagram, Facebook, Linkedin, Youtube, Music2, Twitter, Globe, MessageSquare } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { apiUrl } from "@/lib/api";
import type { Brand } from "@/types";

// Brand colors for each channel (active + configured)
const CHANNEL_STYLES: Record<string, { icon: React.ReactNode; activeColor: string; warnColor: string }> = {
  instagram: {
    icon: <Instagram className="h-3.5 w-3.5" />,
    activeColor: "bg-linear-to-br from-purple-500 via-pink-500 to-orange-400 text-white",
    warnColor: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  },
  facebook: {
    icon: <Facebook className="h-3.5 w-3.5" />,
    activeColor: "bg-[#1877F2] text-white",
    warnColor: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  },
  linkedin: {
    icon: <Linkedin className="h-3.5 w-3.5" />,
    activeColor: "bg-[#0A66C2] text-white",
    warnColor: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  },
  youtube: {
    icon: <Youtube className="h-3.5 w-3.5" />,
    activeColor: "bg-[#FF0000] text-white",
    warnColor: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  },
  tiktok: {
    icon: <Music2 className="h-3.5 w-3.5" />,
    activeColor: "bg-black text-white dark:bg-white dark:text-black",
    warnColor: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  },
  x: {
    icon: <Twitter className="h-3.5 w-3.5" />,
    activeColor: "bg-black text-white dark:bg-white dark:text-black",
    warnColor: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  },
  website_blog: {
    icon: <Globe className="h-3.5 w-3.5" />,
    activeColor: "bg-emerald-600 text-white",
    warnColor: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  },
  teams: {
    icon: <MessageSquare className="h-3.5 w-3.5" />,
    activeColor: "bg-[#6264A7] text-white",
    warnColor: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  },
};

interface BrandCardProps {
  brand: Brand;
}

export function BrandCard({ brand }: BrandCardProps) {
  const initials = brand.name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  // Extract enabled channels from brand_guidelines
  const guidelines = (brand.brand_guidelines || {}) as Record<string, unknown>;
  const channels = (guidelines.channels || {}) as Record<string, Record<string, unknown>>;
  const enabledChannels = Object.entries(channels)
    .filter(([, cfg]) => cfg?.enabled)
    .map(([ch]) => ch);

  return (
    <Link href={`/brands/${brand.id}`}>
      <Card className="hover:shadow-md transition-shadow cursor-pointer h-full">
        <CardContent className="p-4 space-y-4">
          {/* Header: Avatar + Name + Status */}
          <div className="flex items-start gap-3">
            <Avatar className="h-12 w-12 shrink-0">
              <AvatarImage src={brand.logo_url ? apiUrl(brand.logo_url) : undefined} />
              <AvatarFallback className="bg-primary/10 text-primary font-bold">
                {initials}
              </AvatarFallback>
            </Avatar>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-semibold truncate">{brand.name}</h3>
                {brand.status === 'active' ? (
                  <span className="h-2.5 w-2.5 rounded-full bg-green-500 shrink-0" title="Active" />
                ) : brand.status === 'activating' ? (
                  <span className="flex items-center gap-1.5 shrink-0">
                    <span className="h-2.5 w-2.5 rounded-full bg-cyan-500 animate-pulse shrink-0" title="Setting up..." />
                    <span className="text-[10px] text-cyan-600 dark:text-cyan-400 font-medium">Setting up...</span>
                  </span>
                ) : brand.status === 'onboarding' ? (
                  <span className="flex items-center gap-1.5 shrink-0">
                    <span className="h-2.5 w-2.5 rounded-full bg-orange-500 shrink-0" title="Setup required" />
                    <span className="text-[10px] text-orange-600 dark:text-orange-400 font-medium">Setup required</span>
                  </span>
                ) : (
                  <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground shrink-0" title="Inactive" />
                )}
              </div>
              {brand.description && (
                <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{brand.description}</p>
              )}
            </div>
          </div>

          {/* Badges row */}
          <div className="flex flex-wrap gap-1.5">
            {brand.is_bc_linked && (
              <Badge className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 text-[10px]">
                BC Linked
              </Badge>
            )}
            {enabledChannels.length > 0 && (
              <Badge className="bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200 text-[10px]">
                {enabledChannels.length} Channel{enabledChannels.length !== 1 ? "s" : ""}
              </Badge>
            )}
            <Badge variant="outline" className="text-[10px]">
              0% Engagement
            </Badge>
          </div>

          {/* Channels: icon row — 3 states: off (grey), enabled not configured (amber), active (brand color) */}
          <div className="flex gap-1.5">
            {Object.entries(CHANNEL_STYLES).map(([ch, style]) => {
              const cfg = channels[ch] as Record<string, unknown> | undefined;
              const isEnabled = cfg?.enabled;
              const isConfigured = cfg?.configured;

              let className = "bg-muted/50 text-muted-foreground/30"; // off
              let title = ch.replace("_", " ") + " — disabled";

              if (isEnabled && isConfigured) {
                className = style.activeColor;
                title = ch.replace("_", " ") + " — active";
              } else if (isEnabled && !isConfigured) {
                className = style.warnColor;
                title = ch.replace("_", " ") + " — needs setup";
              }

              return (
                <span
                  key={ch}
                  className={`flex items-center justify-center h-7 w-7 rounded-md transition-colors ${className}`}
                  title={title}
                >
                  {style.icon}
                </span>
              );
            })}
          </div>

          {/* BC info: company + locations on same line */}
          {(brand.bc_company || (brand.bc_locations && brand.bc_locations.length > 0)) && (
            <div className="flex items-center gap-3 text-xs text-muted-foreground border-t pt-3">
              {brand.bc_company && (
                <span className="flex items-center gap-1 truncate">
                  <Building2 className="h-3 w-3 shrink-0" />
                  {brand.bc_company}
                </span>
              )}
              {brand.bc_locations && brand.bc_locations.length > 0 && (
                <span className="flex items-center gap-1 truncate">
                  <MapPin className="h-3 w-3 shrink-0" />
                  {brand.bc_locations.join(", ")}
                </span>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
