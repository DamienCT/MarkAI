"use client";

import React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Plus, Trash2 } from "lucide-react";

// A permissive JSON value — report payloads are arbitrary nested data.
export type Json =
  | string
  | number
  | boolean
  | null
  | Json[]
  | { [k: string]: Json };

function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** A blank value shaped like `sample`, used when adding a new array item so
 *  the new entry has the same fields as the existing ones. */
function blankLike(sample: Json): Json {
  if (typeof sample === "number") return 0;
  if (typeof sample === "boolean") return false;
  if (Array.isArray(sample)) return [];
  if (sample && typeof sample === "object") {
    const out: { [k: string]: Json } = {};
    for (const k of Object.keys(sample)) {
      out[k] = blankLike((sample as { [k: string]: Json })[k]);
    }
    return out;
  }
  return ""; // strings, null, undefined
}

function ValueEditor({
  value,
  onChange,
}: {
  value: Json;
  onChange: (v: Json) => void;
}) {
  // ── string ──
  if (typeof value === "string") {
    const multiline = value.length > 70 || value.includes("\n");
    return multiline ? (
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={Math.min(24, Math.max(3, value.split("\n").length + 1))}
      />
    ) : (
      <Input value={value} onChange={(e) => onChange(e.target.value)} />
    );
  }

  // ── number ──
  if (typeof value === "number") {
    return (
      <Input
        type="number"
        value={Number.isFinite(value) ? value : ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? 0 : Number(e.target.value))
        }
      />
    );
  }

  // ── boolean ──
  if (typeof value === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="h-4 w-4"
          checked={value}
          onChange={(e) => onChange(e.target.checked)}
        />
        {value ? "Yes" : "No"}
      </label>
    );
  }

  // ── array ──
  if (Array.isArray(value)) {
    return (
      <div className="space-y-2 border-l-2 border-muted pl-3">
        {value.map((item, i) => (
          <div key={i} className="rounded-md border p-2 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">#{i + 1}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 px-1 text-red-500 hover:text-red-600"
                onClick={() => onChange(value.filter((_, j) => j !== i))}
                title="Remove this item"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
            <ValueEditor
              value={item}
              onChange={(nv) =>
                onChange(value.map((it, j) => (j === i ? nv : it)))
              }
            />
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 gap-1 text-xs"
          onClick={() =>
            onChange([...value, value.length > 0 ? blankLike(value[0]) : ""])
          }
        >
          <Plus className="h-3.5 w-3.5" /> Add
        </Button>
      </div>
    );
  }

  // ── object ──
  if (value && typeof value === "object") {
    const obj = value as { [k: string]: Json };
    return (
      <div className="space-y-2">
        {Object.keys(obj).map((k) => (
          <div key={k} className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              {humanize(k)}
            </label>
            <ValueEditor
              value={obj[k]}
              onChange={(nv) => onChange({ ...obj, [k]: nv })}
            />
          </div>
        ))}
      </div>
    );
  }

  // ── null / unknown → editable as text ──
  return <Input value="" onChange={(e) => onChange(e.target.value)} />;
}

/** Generic editor for a report's editable content. Renders one labeled
 *  section per top-level key; nested objects/arrays are edited recursively
 *  with add/remove controls. */
export function ReportContentEditor({
  data,
  onChange,
}: {
  data: { [k: string]: Json };
  onChange: (d: { [k: string]: Json }) => void;
}) {
  const keys = Object.keys(data);
  if (keys.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nothing to edit for this report.
      </p>
    );
  }
  return (
    <div className="space-y-5">
      {keys.map((key) => (
        <div key={key} className="space-y-2">
          <h4 className="text-sm font-semibold">{humanize(key)}</h4>
          <ValueEditor
            value={data[key]}
            onChange={(nv) => onChange({ ...data, [key]: nv })}
          />
        </div>
      ))}
    </div>
  );
}
