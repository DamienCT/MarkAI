"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import type { Brand, Event } from "@/types";

const GLOBAL_VALUE = "__global__";

interface DetectEventsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  brands: Brand[];
  defaultBrandId?: string | null;
  onDetected: () => void;
}

export function DetectEventsDialog({
  open,
  onOpenChange,
  brands,
  defaultBrandId,
  onDetected,
}: DetectEventsDialogProps) {
  const [brandScope, setBrandScope] = useState<string>(GLOBAL_VALUE);
  const [horizon, setHorizon] = useState<number>(12);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (!open) return;
    setBrandScope(defaultBrandId ?? GLOBAL_VALUE);
    setHorizon(12);
  }, [open, defaultBrandId]);

  const handleDetect = async () => {
    if (horizon < 1 || horizon > 24) {
      toast.error("Horizon must be between 1 and 24 months");
      return;
    }
    setRunning(true);
    try {
      const body = {
        brand_id: brandScope === GLOBAL_VALUE ? null : brandScope,
        horizon_months: horizon,
      };
      const created = await api.post<Event[]>("/api/v1/events/detect", body);
      toast.success(
        created.length === 0
          ? "No new events detected — nothing to add."
          : `Added ${created.length} event${created.length === 1 ? "" : "s"}`
      );
      onOpenChange(false);
      onDetected();
    } catch (err: unknown) {
      const msg =
        (err as { detail?: string })?.detail ??
        (err instanceof Error ? err.message : "Failed to detect events");
      toast.error(msg);
    } finally {
      setRunning(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4" />
            Detect Events
          </DialogTitle>
          <DialogDescription>
            Ask the AI to populate relevant holidays, awareness days, and
            industry moments. Existing entries won&apos;t be duplicated.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="detect-scope">Scope</Label>
            <Select value={brandScope} onValueChange={setBrandScope}>
              <SelectTrigger id="detect-scope">
                <SelectValue placeholder="Scope" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={GLOBAL_VALUE}>Global (all brands)</SelectItem>
                {brands.map((b) => (
                  <SelectItem key={b.id} value={b.id}>
                    {b.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Brand scope gives the AI industry + location context for more
              relevant picks.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="detect-horizon">Horizon (months)</Label>
            <Input
              id="detect-horizon"
              type="number"
              min={1}
              max={24}
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
            />
            <p className="text-xs text-muted-foreground">
              Default 12 months matches the research/calendar planning window.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={running}
          >
            Cancel
          </Button>
          <Button onClick={handleDetect} disabled={running}>
            {running ? "Detecting..." : "Detect"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
