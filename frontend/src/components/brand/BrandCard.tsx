"use client";

import React from "react";
import Link from "next/link";
import { Globe, ExternalLink } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { statusColor } from "@/lib/utils";
import type { Brand } from "@/types";

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

  return (
    <Link href={`/brands/${brand.id}`}>
      <Card className="hover:shadow-md transition-shadow cursor-pointer h-full">
        <CardHeader className="flex flex-row items-center gap-4">
          <Avatar className="h-12 w-12">
            <AvatarImage src={brand.logo_url || undefined} />
            <AvatarFallback className="bg-primary/10 text-primary font-bold">
              {initials}
            </AvatarFallback>
          </Avatar>
          <div className="flex-1">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">{brand.name}</h3>
              <Badge className={statusColor(brand.status)} variant="outline">
                {brand.status}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">{brand.industry}</p>
          </div>
        </CardHeader>
        <CardContent>
          {brand.description && (
            <p className="text-sm text-muted-foreground line-clamp-2 mb-3">{brand.description}</p>
          )}
          <div className="flex items-center justify-between">
            <div className="flex gap-1">
              {brand.social_accounts.map((account, i) => (
                <Badge key={i} variant="outline" className="text-[10px] capitalize">
                  {account.platform}
                </Badge>
              ))}
              {brand.social_accounts.length === 0 && (
                <span className="text-xs text-muted-foreground">No social accounts</span>
              )}
            </div>
            {brand.website_url && (
              <Globe className="h-4 w-4 text-muted-foreground" />
            )}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
