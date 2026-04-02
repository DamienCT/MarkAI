"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface ColorPaletteValue {
  primary: string;
  secondary: string;
  accent: string;
}

interface ColorPaletteProps {
  value: ColorPaletteValue;
  onChange: (palette: ColorPaletteValue) => void;
}

const COLOR_SLOTS: { key: keyof ColorPaletteValue; label: string }[] = [
  { key: "primary", label: "Primary" },
  { key: "secondary", label: "Secondary" },
  { key: "accent", label: "Accent" },
];

const HEX_REGEX = /^#[0-9A-Fa-f]{6}$/;

function ColorSlot({
  label,
  color,
  onChange,
}: {
  label: string;
  color: string;
  onChange: (hex: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [hexInput, setHexInput] = useState(color);
  const popoverRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Sync hex input when color changes externally
  useEffect(() => {
    setHexInput(color);
  }, [color]);

  // Close popover on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const handleHexChange = useCallback(
    (value: string) => {
      // Ensure # prefix
      let hex = value.startsWith("#") ? value : `#${value}`;
      // Limit to 7 chars
      hex = hex.slice(0, 7);
      setHexInput(hex);
      if (HEX_REGEX.test(hex)) {
        onChange(hex);
      }
    },
    [onChange]
  );

  const handleColorPickerChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const hex = e.target.value;
      setHexInput(hex);
      onChange(hex);
    },
    [onChange]
  );

  return (
    <div className="relative flex flex-col items-center gap-2">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(!open)}
        className="group relative h-12 w-12 rounded-xl border-2 border-border shadow-sm transition-all hover:scale-105 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        style={{ backgroundColor: color }}
        title={`${label}: ${color}`}
      >
        <span className="sr-only">Pick {label} color</span>
      </button>
      <div className="text-center">
        <p className="text-xs font-medium text-foreground">{label}</p>
        <p className="text-[11px] font-mono text-muted-foreground uppercase">
          {color}
        </p>
      </div>

      {open && (
        <div
          ref={popoverRef}
          className="absolute top-16 z-50 w-52 rounded-lg border bg-popover p-3 shadow-lg"
        >
          <div className="space-y-3">
            <Label className="text-xs font-medium">{label} Color</Label>

            {/* Native color picker */}
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={color}
                onChange={handleColorPickerChange}
                className="h-9 w-9 cursor-pointer rounded border-0 bg-transparent p-0 [&::-webkit-color-swatch-wrapper]:p-0 [&::-webkit-color-swatch]:rounded [&::-webkit-color-swatch]:border-border [&::-moz-color-swatch]:rounded [&::-moz-color-swatch]:border-border"
              />
              <Input
                value={hexInput}
                onChange={(e) => handleHexChange(e.target.value)}
                className="h-9 font-mono text-xs uppercase"
                placeholder="#000000"
                maxLength={7}
              />
            </div>

            {/* Validation hint */}
            {hexInput.length > 1 && !HEX_REGEX.test(hexInput) && (
              <p className="text-[10px] text-destructive">
                Enter a valid 6-digit hex (e.g. #FF5500)
              </p>
            )}

            {/* Preview swatch */}
            <div
              className="h-8 w-full rounded-md border"
              style={{ backgroundColor: HEX_REGEX.test(hexInput) ? hexInput : color }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export function ColorPalette({ value, onChange }: ColorPaletteProps) {
  const handleSlotChange = useCallback(
    (key: keyof ColorPaletteValue, hex: string) => {
      onChange({ ...value, [key]: hex });
    },
    [value, onChange]
  );

  return (
    <div className="space-y-3">
      <Label className="text-sm font-medium">Brand Colors</Label>
      <div className="flex items-start gap-6">
        {COLOR_SLOTS.map((slot) => (
          <ColorSlot
            key={slot.key}
            label={slot.label}
            color={value[slot.key]}
            onChange={(hex) => handleSlotChange(slot.key, hex)}
          />
        ))}

        {/* Live preview bar */}
        <div className="ml-auto flex flex-col items-center gap-2">
          <div className="flex h-12 overflow-hidden rounded-xl border shadow-sm">
            <div className="w-16" style={{ backgroundColor: value.primary }} />
            <div className="w-10" style={{ backgroundColor: value.secondary }} />
            <div className="w-6" style={{ backgroundColor: value.accent }} />
          </div>
          <p className="text-xs text-muted-foreground">Preview</p>
        </div>
      </div>
    </div>
  );
}
