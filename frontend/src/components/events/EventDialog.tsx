"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
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
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import type { Brand, Event, EventCreate, EventUpdate } from "@/types";

const GLOBAL_VALUE = "__global__";

const CATEGORIES = [
  { value: "holiday", label: "Holiday" },
  { value: "awareness", label: "Awareness" },
  { value: "industry", label: "Industry" },
  { value: "local", label: "Local" },
  { value: "custom", label: "Custom" },
];

interface EventDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  brands: Brand[];
  event?: Event | null;
  defaultBrandId?: string | null;
  onSaved: () => void;
}

export function EventDialog({
  open,
  onOpenChange,
  brands,
  event,
  defaultBrandId,
  onSaved,
}: EventDialogProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [isAnnual, setIsAnnual] = useState(true);
  const [category, setCategory] = useState<string>("holiday");
  const [brandScope, setBrandScope] = useState<string>(GLOBAL_VALUE);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (event) {
      setTitle(event.title);
      setDescription(event.description ?? "");
      setStartDate(event.start_date);
      setEndDate(event.end_date ?? "");
      setIsAnnual(event.is_annual);
      setCategory(event.category ?? "holiday");
      setBrandScope(event.brand_id ?? GLOBAL_VALUE);
    } else {
      setTitle("");
      setDescription("");
      setStartDate("");
      setEndDate("");
      setIsAnnual(true);
      setCategory("holiday");
      setBrandScope(defaultBrandId ?? GLOBAL_VALUE);
    }
  }, [open, event, defaultBrandId]);

  const handleSave = async () => {
    if (!title.trim()) {
      toast.error("Title is required");
      return;
    }
    if (!startDate) {
      toast.error("Start date is required");
      return;
    }
    if (endDate && endDate < startDate) {
      toast.error("End date must be on or after start date");
      return;
    }

    const payload: EventCreate | EventUpdate = {
      title: title.trim(),
      description: description.trim() || null,
      start_date: startDate,
      end_date: endDate || null,
      is_annual: isAnnual,
      category: category || null,
      brand_id: brandScope === GLOBAL_VALUE ? null : brandScope,
    };

    setSaving(true);
    try {
      if (event) {
        await api.put<Event>(`/api/v1/events/${event.id}`, payload);
        toast.success("Event updated");
      } else {
        await api.post<Event>("/api/v1/events", payload);
        toast.success("Event created");
      }
      onOpenChange(false);
      onSaved();
    } catch (err: unknown) {
      const msg =
        (err as { detail?: string })?.detail ??
        (err instanceof Error ? err.message : "Failed to save event");
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{event ? "Edit Event" : "Add Event"}</DialogTitle>
          <DialogDescription>
            Events flagged here are injected into research context so the
            marketing plan anchors to real dates.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="event-title">Title *</Label>
            <Input
              id="event-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Mother's Day"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="event-description">Description</Label>
            <Textarea
              id="event-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional short note — appears in research context"
              rows={2}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="event-start">Start date *</Label>
              <Input
                id="event-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="event-end">End date</Label>
              <Input
                id="event-end"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="event-category">Category</Label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger id="event-category">
                  <SelectValue placeholder="Category" />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c.value} value={c.value}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="event-scope">Scope</Label>
              <Select value={brandScope} onValueChange={setBrandScope}>
                <SelectTrigger id="event-scope">
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
            </div>
          </div>

          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <Label htmlFor="event-annual" className="text-sm font-medium">
                Annual
              </Label>
              <p className="text-xs text-muted-foreground">
                When on, the event recurs every year (month/day only).
              </p>
            </div>
            <Switch
              id="event-annual"
              checked={isAnnual}
              onCheckedChange={setIsAnnual}
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : event ? "Update" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
