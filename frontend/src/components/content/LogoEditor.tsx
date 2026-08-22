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
 *  - the Save (✓) / Cancel (✕) buttons commit or discard
 *  - Escape also cancels
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Move, RefreshCw, Layers, Grid3x3, Type, Check, X, Tag } from "lucide-react";

export interface LogoPlacement {
  logo_xy: [number, number];
  logo_scale: number;
  text_xy: [number, number] | null;
  text_scale: number;
  logo_variant?: string;
  text_style?: string; // "glass" | "solid" | "headline"
  font_family?: string; // headline font (e.g. "Montserrat")
  headline_colors?: Record<string, string>; // word index -> "#RRGGBB"
  text_width?: number; // headline wrap width as a fraction of image width (0..1)
  product_logo_xy?: [number, number]; // product (manufacturer) logo center (0..1)
  product_logo_scale?: number; // product logo width as a fraction of image width
  product_logo_enabled?: boolean; // show/hide the product logo
  product_logo_variant?: string; // "light" | "dark" manual override (else auto)
}

// Bundled headline fonts (match agents Dockerfile + image_processing.HEADLINE_FONTS).
export const HEADLINE_FONTS = [
  "Montserrat",
  "Poppins",
  "Oswald",
  "Playfair Display",
  "Dancing Script",
];

interface LogoEditorProps {
  cleanImageUrl: string;
  logoUrl?: string;
  /** The product (manufacturer) logo, if the linked product has one. */
  productLogoUrl?: string;
  /** Light/dark variant URLs of the vendor logo (for the manual swap button). */
  productLogoUrls?: { light?: string | null; dark?: string | null };
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

// Server text-card font size is 3.0% of image width — mirror it so the
// editor preview matches the final PIL render proportionally.
const FONT_LARGE_FRAC = 0.03;

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

type DragKind =
  | "move-logo"
  | "resize-logo"
  | "move-text"
  | "resize-text"
  | "resize-text-w"
  | "move-product-logo"
  | "resize-product-logo";
interface DragState {
  kind: DragKind;
  startClientX: number;
  startClientY: number;
  startXy: [number, number];
  startScale: number;
  startWidth: number;
  rectW: number;
  rectH: number;
}

export function LogoEditor({
  cleanImageUrl,
  logoUrl,
  productLogoUrl,
  productLogoUrls,
  textLine1,
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

  // Product (manufacturer) logo — a 2nd draggable/resizable logo, on/off.
  const [productLogoXy, setProductLogoXy] = useState<[number, number]>(
    initial.product_logo_xy || [0.12, 0.88]
  );
  const [productLogoScale, setProductLogoScale] = useState<number>(
    initial.product_logo_scale || 0.18
  );
  const [productLogoEnabled, setProductLogoEnabled] = useState<boolean>(
    initial.product_logo_enabled !== false && !!productLogoUrl
  );
  // Vendor logo light/dark variant — cycled manually with a button (like the
  // brand logo's reverse button). The chosen value overrides the renderer's
  // background-based auto-pick. Available variants come from productLogoUrls.
  const plLightUrl = productLogoUrls?.light || productLogoUrl || undefined;
  const plDarkUrl = productLogoUrls?.dark || undefined;
  const plHasBoth = !!plLightUrl && !!plDarkUrl;
  const [productLogoVariant, setProductLogoVariant] = useState<"light" | "dark">(
    initial.product_logo_variant === "dark"
      ? "dark"
      : initial.product_logo_variant === "light"
        ? "light"
        : plLightUrl ? "light" : "dark"
  );
  const cycleProductLogoVariant = useCallback(
    () => setProductLogoVariant((v) => (v === "light" ? "dark" : "light")),
    []
  );
  // The variant actually shown in the preview (fall back if one is missing).
  const effectiveProductLogoUrl =
    (productLogoVariant === "dark" ? plDarkUrl : plLightUrl) ||
    plLightUrl || plDarkUrl;
  const [textXy, setTextXy] = useState<[number, number]>(
    initial.text_xy || anchorToXy(initial.textAnchor)
  );
  const [textScale, setTextScale] = useState<number>(initial.text_scale || 1);
  // Text style: "glass" (frosted card) | "solid" (dark panel) | "headline"
  // (large bold title, no card — the ad/poster look).
  const [textStyle, setTextStyle] = useState<string>(
    ["solid", "headline", "none"].includes(initial.text_style || "") ? initial.text_style! : "glass"
  );
  // Cycle: glass → solid → headline → none (no text) → glass …
  const toggleTextStyle = useCallback(
    () =>
      setTextStyle((s) =>
        s === "glass" ? "solid"
          : s === "solid" ? "headline"
          : s === "headline" ? "none"
          : "glass"
      ),
    []
  );
  const isHeadline = textStyle === "headline";
  const isNone = textStyle === "none";

  // Overlay font (cycled with a button, like the logo variant). Applies to any
  // text style — glass / solid / headline.
  const [fontFamily, setFontFamily] = useState<string>(
    HEADLINE_FONTS.includes(initial.font_family || "") ? initial.font_family! : HEADLINE_FONTS[0]
  );
  const cycleFont = useCallback(
    () => setFontFamily((f) => {
      const i = HEADLINE_FONTS.indexOf(f);
      return HEADLINE_FONTS[(i + 1) % HEADLINE_FONTS.length];
    }),
    []
  );

  // Per-word headline colors (index -> "#RRGGBB"). Click a word in the preview
  // to open the native color picker; only that word changes. White by default.
  const [headlineColors, setHeadlineColors] = useState<Record<string, string>>(
    initial.headline_colors && typeof initial.headline_colors === "object"
      ? { ...initial.headline_colors }
      : {}
  );
  const colorInputRef = useRef<HTMLInputElement | null>(null);
  const colorWordRef = useRef<number | null>(null);
  const pickColorForWord = useCallback((idx: number) => {
    colorWordRef.current = idx;
    const input = colorInputRef.current;
    if (!input) return;
    input.value = headlineColors[String(idx)] || "#ffffff";
    input.click();
  }, [headlineColors]);
  const applyWordColor = useCallback((hex: string) => {
    const idx = colorWordRef.current;
    if (idx == null) return;
    setHeadlineColors((c) => {
      const next = { ...c };
      // White = the default, so storing it is the same as clearing the override.
      if (hex.toLowerCase() === "#ffffff") delete next[String(idx)];
      else next[String(idx)] = hex;
      return next;
    });
  }, []);
  const resetColors = useCallback(() => setHeadlineColors({}), []);
  const headlineWords = (textLine1 || "Titre").split(/\s+/).filter(Boolean);

  // Canva-style wrap width for the headline box (fraction of image width).
  // The right-edge handle drags this: wider = fewer line breaks, narrower =
  // text re-wraps onto more lines. Height auto-adjusts; NO letter distortion.
  // Default 0.86 mirrors the backend (image_processing max_w) so edit == render.
  const HEADLINE_WIDTH_DEFAULT = 0.86;
  const [textWidth, setTextWidth] = useState<number>(
    typeof initial.text_width === "number" ? initial.text_width : HEADLINE_WIDTH_DEFAULT
  );

  // Alignment grid (rule-of-thirds), like a photo editor. On by default.
  const [showGrid, setShowGrid] = useState(true);

  // While a drag is in progress, fade the floating controls out of the way so
  // they don't visually block (and can't intercept) a logo dragged underneath.
  const [dragging, setDragging] = useState(false);

  // Logo variant (dark = white logo, light = dark logo, …). The reverse button
  // cycles only through these, in this order — watermark/secondary excluded.
  // Memoized so cycleVariant's useCallback deps stay stable across renders.
  const variantKeys = useMemo(() => {
    const VARIANT_ORDER = ["primary", "dark", "light", "icon"];
    return logos
      ? (VARIANT_ORDER
          .map((want) => Object.keys(logos).find((k) => k.toLowerCase() === want))
          .filter(Boolean) as string[])
      : [];
  }, [logos]);
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

  // Keep the latest placement in a ref so the Save button reads fresh values
  // without re-creating its handler on every drag tick.
  const placementRef = useRef<LogoPlacement>({
    logo_xy: logoXy, logo_scale: logoScale, text_xy: textXy, text_scale: textScale,
  });
  // Sync after every render (refs must not be written during render); Save
  // fires from an event handler, which always runs after effects have synced.
  useEffect(() => {
    placementRef.current = {
      logo_xy: logoXy, logo_scale: logoScale, text_xy: textXy,
      text_scale: textScale, logo_variant: variant || undefined,
      text_style: textStyle,
      font_family: isNone ? undefined : fontFamily,
      headline_colors: isHeadline ? headlineColors : undefined,
      text_width: isHeadline ? textWidth : undefined,
      ...(productLogoUrl
        ? {
            product_logo_xy: productLogoXy,
            product_logo_scale: productLogoScale,
            product_logo_enabled: productLogoEnabled,
            // Only pin a variant when both exist (else leave auto-pick on).
            product_logo_variant: plHasBoth ? productLogoVariant : undefined,
          }
        : {}),
    };
  });

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
    } else if (d.kind === "resize-text-w") {
      // Wrap width: dragging right widens the box (×2 → full box from center),
      // so the text re-wraps onto fewer/more lines instead of distorting.
      setTextWidth(clamp(d.startWidth + dx * 2, 0.3, 0.97));
    } else if (d.kind === "move-product-logo") {
      setProductLogoXy([clamp(d.startXy[0] + dx, 0.02, 0.98), clamp(d.startXy[1] + dy, 0.02, 0.98)]);
    } else if (d.kind === "resize-product-logo") {
      setProductLogoScale(clamp(d.startScale + dx, 0.05, 0.5));
    }
  }, []);

  const endDrag = useCallback(() => {
    dragRef.current = null;
    setDragging(false);
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
    const startXy =
      kind === "move-logo" ? logoXy
      : kind === "move-product-logo" ? productLogoXy
      : textXy;
    const startScale =
      kind === "resize-logo" ? logoScale
      : kind === "resize-product-logo" ? productLogoScale
      : textScale;
    dragRef.current = {
      kind,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startXy,
      startScale,
      startWidth: textWidth,
      rectW: r?.width || 1,
      rectH: r?.height || 1,
    };
    setDragging(true);
  };

  // ── Escape → cancel (save/cancel are explicit buttons now) ─────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const logoWpx = dims.w * logoScale;
  const fontLargePx = Math.max(8, dims.w * FONT_LARGE_FRAC * textScale);

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

  // Edge handle (headline only): right = wrap width (re-wraps the text).
  const edgeHandleRight: React.CSSProperties = {
    position: "absolute",
    right: -7,
    top: "50%",
    transform: "translateY(-50%)",
    width: 12,
    height: 26,
    borderRadius: 4,
    background: "#2563eb",
    border: "2px solid white",
    cursor: "ew-resize",
    touchAction: "none",
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Move className="h-3.5 w-3.5" /> Drag to move · blue corner to resize
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            title="Cancel (Esc)"
            aria-label="Cancel"
            className="flex h-8 w-8 items-center justify-center rounded-md border bg-white text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onSave(placementRef.current)}
            disabled={saving}
            title="Save"
            aria-label="Save"
            className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-600 text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          </button>
        </div>
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

        {/* Text card (overlay) — hidden entirely when the overlay is removed. */}
        {isNone ? null : (
        <div
          onPointerDown={startDrag("move-text")}
          style={{
            position: "absolute",
            left: `${textXy[0] * 100}%`,
            top: `${textXy[1] * 100}%`,
            transform: "translate(-50%, -50%)",
            // Headline: a FIXED-width box (= the wrap width) so the browser
            // wraps at the SAME point as the PIL render (edit == rendering).
            // Other styles: max-content sizes the card to its text (so it
            // doesn't fold into a square when dragged right), capped at 72%.
            width: isHeadline ? `${textWidth * 100}%` : "max-content",
            maxWidth: isHeadline ? `${textWidth * 100}%` : "72%",
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
          <div style={{
            fontSize: isHeadline ? fontLargePx * 2 : fontLargePx,
            lineHeight: 1.15,
            fontWeight: isHeadline ? 800 : 500,
            fontFamily: `"${fontFamily}", sans-serif`,
          }}>
            {isHeadline
              ? headlineWords.map((w, i) => (
                  <React.Fragment key={i}>
                    <span
                      onPointerDown={(e) => { e.stopPropagation(); }}
                      onClick={(e) => { e.stopPropagation(); pickColorForWord(i); }}
                      title="Click to color this word"
                      style={{
                        color: headlineColors[String(i)] || "#ffffff",
                        cursor: "pointer",
                      }}
                    >
                      {w}
                    </span>
                    {i < headlineWords.length - 1 ? " " : ""}
                  </React.Fragment>
                ))
              : (textLine1 || "Titre")}
          </div>
          {/* Brand/website subtitle ("link") intentionally removed from the
              glass & solid overlays — only the headline line is shown. */}
          {/* Corner = font size (proportional). For the headline, the right
              edge handle changes the WRAP WIDTH so the text re-flows onto more
              or fewer lines (Canva-style) — no distortion. */}
          <div onPointerDown={startDrag("resize-text")} style={handleStyle} title="Size" />
          {isHeadline ? (
            <div onPointerDown={startDrag("resize-text-w")} style={edgeHandleRight} title="Wrap width" />
          ) : null}
        </div>
        )}

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

        {/* Product (manufacturer) logo — draggable + resizable, toggle on/off */}
        {productLogoUrl && productLogoEnabled ? (
          <div
            onPointerDown={startDrag("move-product-logo")}
            style={{
              position: "absolute",
              left: `${productLogoXy[0] * 100}%`,
              top: `${productLogoXy[1] * 100}%`,
              transform: "translate(-50%, -50%)",
              width: dims.w * productLogoScale,
              cursor: "move",
              touchAction: "none",
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={effectiveProductLogoUrl}
              alt="product logo"
              className="block w-full"
              draggable={false}
              style={{ filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.4))" }}
            />
            <div onPointerDown={startDrag("resize-product-logo")} style={handleStyle} />
          </div>
        ) : null}

        {/* Style controls, overlaid on the photo frame. */}
        <div
          className={`absolute left-2 top-2 z-20 flex flex-col items-start gap-1.5 transition-opacity duration-150 ${
            dragging ? "pointer-events-none opacity-20" : "pointer-events-none"
          }`}
        >
          {variantKeys.length >= 2 ? (
            <button
              type="button"
              onPointerDown={(e) => { e.stopPropagation(); }}
              onClick={cycleVariant}
              className="pointer-events-auto flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-xs font-medium text-black shadow hover:bg-white"
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
            className="pointer-events-auto flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-xs font-medium text-black shadow hover:bg-white"
            title="Cycle text style (glass / solid / headline)"
          >
            <Layers className="h-3.5 w-3.5" />
            Overlay: {textStyle}
          </button>
          {productLogoUrl ? (
            <button
              type="button"
              onPointerDown={(e) => { e.stopPropagation(); }}
              onClick={() => setProductLogoEnabled((v) => !v)}
              className={`pointer-events-auto flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium shadow ${productLogoEnabled ? "bg-blue-600 text-white hover:bg-blue-700" : "bg-white/90 text-black hover:bg-white"}`}
              title="Show/hide the product (manufacturer) logo"
            >
              <Tag className="h-3.5 w-3.5" />
              Product logo: {productLogoEnabled ? "on" : "off"}
            </button>
          ) : null}
          {productLogoUrl && productLogoEnabled && plHasBoth ? (
            <button
              type="button"
              onPointerDown={(e) => { e.stopPropagation(); }}
              onClick={cycleProductLogoVariant}
              className="pointer-events-auto flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-xs font-medium text-black shadow hover:bg-white"
              title="Swap the vendor logo variant (light = light bg, dark = dark bg)"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Vendor logo: {productLogoVariant}
            </button>
          ) : null}
          {!isNone ? (
            <button
              type="button"
              onPointerDown={(e) => { e.stopPropagation(); }}
              onClick={cycleFont}
              className="pointer-events-auto flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-xs font-medium text-black shadow hover:bg-white"
              title="Cycle overlay font"
            >
              <Type className="h-3.5 w-3.5" />
              Font: {fontFamily}
            </button>
          ) : null}
          {isHeadline && Object.keys(headlineColors).length > 0 ? (
            <button
              type="button"
              onPointerDown={(e) => { e.stopPropagation(); }}
              onClick={resetColors}
              className="pointer-events-auto flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-xs font-medium text-black shadow hover:bg-white"
              title="Reset all word colors to white"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Reset colors
            </button>
          ) : null}
          <button
            type="button"
            onPointerDown={(e) => { e.stopPropagation(); }}
            onClick={() => setShowGrid((g) => !g)}
            className={`pointer-events-auto flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium shadow ${showGrid ? "bg-blue-600 text-white hover:bg-blue-700" : "bg-white/90 text-black hover:bg-white"}`}
            title="Toggle alignment grid"
          >
            <Grid3x3 className="h-3.5 w-3.5" />
            Grid: {showGrid ? "on" : "off"}
          </button>
        </div>

        {/* Hidden native color picker, opened by clicking a headline word. */}
        <input
          ref={colorInputRef}
          type="color"
          className="pointer-events-none absolute h-0 w-0 opacity-0"
          onPointerDown={(e) => { e.stopPropagation(); }}
          onInput={(e) => applyWordColor((e.target as HTMLInputElement).value)}
          onChange={(e) => applyWordColor((e.target as HTMLInputElement).value)}
        />

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
