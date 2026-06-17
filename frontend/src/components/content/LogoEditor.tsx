"use client";

/**
 * Canva-style visual editor for the logo + text overlay on a generated post.
 *
 * The backdrop is the CLEAN composed image (no logo/text). The logo and the
 * text card are rendered as draggable + resizable elements on top, in
 * NORMALIZED (0..1) center coordinates — the exact convention the backend
 * `overlay_logo_and_text(logo_xy, text_xy, ...)` expects, so what you place
 * here is what the server re-renders.
 *
 * Interactions (pure pointer events, no external dependency):
 *  - drag an element to move it
 *  - drag its corner handle to resize it
 *  - click ANYWHERE outside the photo to save
 *  - Escape to cancel
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Move, RefreshCw, Layers, Grid3x3 } from "lucide-react";

export interface LogoPlacement {
  logo_xy: [number, number];
  logo_scale: number;
  text_xy: [number, number] | null;
  text_scale: number;
  logo_variant?: string;
  text_style?: string; // "glass" | "solid"
}

interface LogoEditorProps {
  cleanImageUrl: string;
  logoUrl?: string;
  textLine1: string;
  textLine2?: string;
  initial: LogoPlacement & { textAnchor?: string | null };
  /** Available logo variants (label → url) for the reverse/swap button. */
  logos?: Record<string, string>;
  initialVariant?: string;
  saving?: boolean;
  onSave: (placement: LogoPlacement) => void;
  onCancel: () => void;
}

// Server text-card font sizes are 3.0% / 1.9% of image width — mirror them
// so the editor preview matches the final PIL render proportionally.
const FONT_LARGE_FRAC = 0.03;
const FONT_SMALL_FRAC = 0.019;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// Approximate a text anchor corner → normalized center, used only when the
// post has never had a free text position saved yet.
function anchorToXy(anchor?: string | null): [number, number] {
  switch (anchor) {
    case "top-left": return [0.3, 0.1];
    case "top-right": return [0.7, 0.1];
    case "bottom-right": return [0.7, 0.9];
    case "bottom-left":
    default: return [0.3, 0.9];
  }
}

type DragKind = "move-logo" | "resize-logo" | "move-text" | "resize-text";
interface DragState {
  kind: DragKind;
  startClientX: number;
  startClientY: number;
  startXy: [number, number];
  startScale: number;
  rectW: number;
  rectH: number;
}

export function LogoEditor({
  cleanImageUrl,
  logoUrl,
  textLine1,
  textLine2,
  initial,
  logos,
  initialVariant,
  saving,
  onSave,
  onCancel,
}: LogoEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });

  const [logoXy, setLogoXy] = useState<[number, number]>(initial.logo_xy || [0.85, 0.85]);
  const [logoScale, setLogoScale] = useState<number>(initial.logo_scale || 0.2);
  const [textXy, setTextXy] = useState<[number, number]>(
    initial.text_xy || anchorToXy(initial.textAnchor)
  );
  const [textScale, setTextScale] = useState<number>(initial.text_scale || 1);
  // Text style: "glass" (frosted card) | "solid" (dark panel) | "headline"
  // (large bold title, no card — the ad/poster look).
  const [textStyle, setTextStyle] = useState<string>(
    ["solid", "headline"].includes(initial.text_style || "") ? initial.text_style! : "glass"
  );
  const toggleTextStyle = useCallback(
    () =>
      setTextStyle((s) =>
        s === "glass" ? "solid" : s === "solid" ? "headline" : "glass"
      ),
    []
  );
  const isHeadline = textStyle === "headline";

  // Alignment grid (rule-of-thirds), like a photo editor. On by default.
  const [showGrid, setShowGrid] = useState(true);

  // Logo variant (dark = white logo, light = dark logo, …). The reverse button
  // cycles only through these, in this order — watermark/secondary excluded.
  const VARIANT_ORDER = ["primary", "dark", "light", "icon"];
  const variantKeys = logos
    ? (VARIANT_ORDER
        .map((want) => Object.keys(logos).find((k) => k.toLowerCase() === want))
        .filter(Boolean) as string[])
    : [];
  const [variant, setVariant] = useState<string>(
    initialVariant && variantKeys.includes(initialVariant)
      ? initialVariant
      : (variantKeys[0] || "")
  );
  const currentLogoUrl = (variant && logos?.[variant]) || logoUrl;
  const cycleVariant = useCallback(() => {
    if (variantKeys.length < 2) return;
    const i = variantKeys.indexOf(variant);
    setVariant(variantKeys[(i + 1) % variantKeys.length]);
  }, [variant, variantKeys]);

  // Keep the latest placement in a ref so the outside-click saver reads fresh
  // values without re-subscribing the listener on every drag tick.
  const placementRef = useRef<LogoPlacement>({
    logo_xy: logoXy, logo_scale: logoScale, text_xy: textXy, text_scale: textScale,
  });
  placementRef.current = {
    logo_xy: logoXy, logo_scale: logoScale, text_xy: textXy,
    text_scale: textScale, logo_variant: variant || undefined,
    text_style: textStyle,
  };

  // So the outside-click saver can bail while a save is already in flight.
  const savingRef = useRef(!!saving);
  savingRef.current = !!saving;

  // Track the rendered photo size for normalized↔pixel math + font sizing.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setDims({ w: r.width, h: r.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ── Pointer drag / resize ──────────────────────────────────────
  const onPointerMove = useCallback((e: PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = (e.clientX - d.startClientX) / (d.rectW || 1);
    const dy = (e.clientY - d.startClientY) / (d.rectH || 1);
    if (d.kind === "move-logo") {
      setLogoXy([clamp(d.startXy[0] + dx, 0.02, 0.98), clamp(d.startXy[1] + dy, 0.02, 0.98)]);
    } else if (d.kind === "move-text") {
      setTextXy([clamp(d.startXy[0] + dx, 0.02, 0.98), clamp(d.startXy[1] + dy, 0.02, 0.98)]);
    } else if (d.kind === "resize-logo") {
      // Width grows with rightward/downward drag; scale = fraction of width.
      setLogoScale(clamp(d.startScale + dx, 0.05, 0.6));
    } else if (d.kind === "resize-text") {
      setTextScale(clamp(d.startScale + dx * 4, 0.5, 2.5));
    }
  }, []);

  const endDrag = useCallback(() => {
    dragRef.current = null;
  }, []);

  useEffect(() => {
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
    };
  }, [onPointerMove, endDrag]);

  const startDrag = (kind: DragKind) => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const r = containerRef.current?.getBoundingClientRect();
    dragRef.current = {
      kind,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startXy: kind.startsWith("move-logo") ? logoXy : textXy,
      startScale: kind.endsWith("logo") ? logoScale : textScale,
      rectW: r?.width || 1,
      rectH: r?.height || 1,
    };
  };

  // ── Click outside the photo → save ─────────────────────────────
  useEffect(() => {
    const onDocPointerDown = (e: PointerEvent) => {
      if (dragRef.current || savingRef.current) return; // mid-interaction / saving
      const el = containerRef.current;
      if (el && !el.contains(e.target as Node)) {
        onSave(placementRef.current);
      }
    };
    // Defer attaching so the click that opened the editor doesn't save it.
    const t = window.setTimeout(() => {
      document.addEventListener("pointerdown", onDocPointerDown, true);
    }, 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(t);
      document.removeEventListener("pointerdown", onDocPointerDown, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [onSave, onCancel]);

  const logoWpx = dims.w * logoScale;
  const fontLargePx = Math.max(8, dims.w * FONT_LARGE_FRAC * textScale);
  const fontSmallPx = Math.max(7, dims.w * FONT_SMALL_FRAC * textScale);

  const handleStyle: React.CSSProperties = {
    position: "absolute",
    right: -8,
    bottom: -8,
    width: 16,
    height: 16,
    borderRadius: 4,
    background: "#2563eb",
    border: "2px solid white",
    cursor: "nwse-resize",
    touchAction: "none",
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Move className="h-3.5 w-3.5" /> Drag to move · blue corner to resize
        </span>
        <span>Click outside the photo to save · Esc to cancel</span>
      </div>

      <div
        ref={containerRef}
        className="relative mx-auto w-full max-w-[520px] overflow-hidden rounded-lg border-2 border-blue-500 shadow-lg select-none"
        style={{ touchAction: "none" }}
      >
        {/* Clean backdrop */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={cleanImageUrl} alt="post" className="block w-full" draggable={false} />

        {/* Alignment grid (rule-of-thirds) — non-interactive, sits under the
            logo/text so it never blocks dragging. */}
        {showGrid ? (
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage:
                "linear-gradient(to right, rgba(255,255,255,0.30) 1px, transparent 1px)," +
                "linear-gradient(to bottom, rgba(255,255,255,0.30) 1px, transparent 1px)",
              backgroundSize: "33.333% 33.333%",
              boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.15)",
            }}
          />
        ) : null}

        {/* Text card (overlay) */}
        <div
          onPointerDown={startDrag("move-text")}
          style={{
            position: "absolute",
            left: `${textXy[0] * 100}%`,
            top: `${textXy[1] * 100}%`,
            transform: "translate(-50%, -50%)",
            // width:max-content sizes the card to its text regardless of its
            // left position — without it, an absolutely-positioned auto-width
            // box shrinks as `left` grows (the "folds into a square" bug when
            // dragged right). maxWidth still caps it at 72% of the photo.
            width: "max-content",
            maxWidth: isHeadline ? "86%" : "72%",
            textAlign: isHeadline ? "center" : "left",
            padding: isHeadline ? 0 : `${Math.max(6, dims.w * 0.012)}px ${Math.max(10, dims.w * 0.016)}px`,
            background: isHeadline ? "transparent" : textStyle === "solid" ? "rgba(12,14,18,0.88)" : "rgba(10,12,16,0.5)",
            borderRadius: isHeadline ? 0 : Math.max(8, dims.w * 0.011),
            border: isHeadline ? "none" : textStyle === "solid" ? "1px solid rgba(255,255,255,0.18)" : "1px solid rgba(255,255,255,0.35)",
            color: "white",
            cursor: "move",
            touchAction: "none",
            backdropFilter: isHeadline || textStyle === "solid" ? "none" : "blur(2px)",
            textShadow: isHeadline ? "0 2px 6px rgba(0,0,0,0.6)" : "none",
          }}
        >
          <div style={{ fontSize: isHeadline ? fontLargePx * 2 : fontLargePx, lineHeight: 1.15, fontWeight: isHeadline ? 800 : 500 }}>
            {textLine1 || "Titre"}
          </div>
          {textLine2 ? (
            <div style={{ fontSize: isHeadline ? fontSmallPx * 1.2 : fontSmallPx, lineHeight: 1.2, opacity: 0.9 }}>
              {textLine2}
            </div>
          ) : null}
          <div onPointerDown={startDrag("resize-text")} style={handleStyle} />
        </div>

        {/* Logo */}
        {currentLogoUrl ? (
          <div
            onPointerDown={startDrag("move-logo")}
            style={{
              position: "absolute",
              left: `${logoXy[0] * 100}%`,
              top: `${logoXy[1] * 100}%`,
              transform: "translate(-50%, -50%)",
              width: logoWpx,
              cursor: "move",
              touchAction: "none",
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={currentLogoUrl}
              alt="logo"
              className="block w-full"
              draggable={false}
              style={{ filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.4))" }}
            />
            <div onPointerDown={startDrag("resize-logo")} style={handleStyle} />
          </div>
        ) : null}

        {/* Style controls — kept INSIDE the frame so clicks don't trigger
            the outside-click save. */}
        <div className="absolute left-2 top-2 z-20 flex flex-col items-start gap-1.5">
          {variantKeys.length >= 2 ? (
            <button
              type="button"
              onPointerDown={(e) => { e.stopPropagation(); }}
              onClick={cycleVariant}
              className="flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-xs font-medium text-black shadow hover:bg-white"
              title="Reverse logo (light / dark)"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {variant ? `Logo: ${variant}` : "Reverse logo"}
            </button>
          ) : null}
          <button
            type="button"
            onPointerDown={(e) => { e.stopPropagation(); }}
            onClick={toggleTextStyle}
            className="flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-xs font-medium text-black shadow hover:bg-white"
            title="Cycle text style (glass / solid / headline)"
          >
            <Layers className="h-3.5 w-3.5" />
            Overlay: {textStyle}
          </button>
          <button
            type="button"
            onPointerDown={(e) => { e.stopPropagation(); }}
            onClick={() => setShowGrid((g) => !g)}
            className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium shadow ${showGrid ? "bg-blue-600 text-white hover:bg-blue-700" : "bg-white/90 text-black hover:bg-white"}`}
            title="Toggle alignment grid"
          >
            <Grid3x3 className="h-3.5 w-3.5" />
            Grid: {showGrid ? "on" : "off"}
          </button>
        </div>

        {/* Saving overlay */}
        {saving ? (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40">
            <div className="flex items-center gap-2 rounded-md bg-white px-3 py-2 text-sm font-medium text-black shadow">
              <Loader2 className="h-4 w-4 animate-spin" /> Rendering…
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
