"use client";

import React from "react";
import { CompetitorTracker } from "@/components/brand/CompetitorTracker";
import type { Competitor } from "@/types";

export interface CompetitorsTabProps {
  brandId: string;
  competitors: Competitor[];
}

export function CompetitorsTab({ brandId, competitors }: CompetitorsTabProps) {
  return (
    <div className="mt-6">
      <CompetitorTracker brandId={brandId} competitors={competitors} />
    </div>
  );
}
