import React, { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { Badge } from "@/components/ui/badge";

// ── Helpers ──────────────────────────────────────────────────────────

/** Convert a flat object like {Kreol: "40%", French: "35%"} to "Kreol 40%, French 35%" */
export function formatKeyValue(obj: Record<string, unknown>): string {
  return Object.entries(obj)
    .map(([k, v]) => `${k} ${String(v)}`)
    .join(", ");
}

function isStringRecord(v: unknown): v is Record<string, string> {
  return (
    typeof v === "object" &&
    v !== null &&
    !Array.isArray(v) &&
    Object.values(v as Record<string, unknown>).every((x) => typeof x === "string")
  );
}

function isUniformObjectArray(
  arr: unknown[]
): arr is Record<string, unknown>[] {
  return arr.length > 0 && arr.every((x) => typeof x === "object" && x !== null && !Array.isArray(x));
}

// ── Core renderer ────────────────────────────────────────────────────

export function renderValue(value: unknown): ReactNode {
  if (value == null) return null;

  if (typeof value === "boolean") {
    return <Badge variant="secondary">{value ? "Yes" : "No"}</Badge>;
  }

  if (typeof value === "number") {
    return <span>{String(value)}</span>;
  }

  if (typeof value === "string") {
    if (value.includes("\n") || value.length > 200) {
      return (
        <div className="prose prose-sm max-w-none dark:prose-invert">
          <ReactMarkdown>{value}</ReactMarkdown>
        </div>
      );
    }
    return <span>{value}</span>;
  }

  if (Array.isArray(value)) {
    // string[] -> badges
    if (value.every((x) => typeof x === "string")) {
      return (
        <div className="flex flex-wrap gap-1.5">
          {value.map((s, i) => (
            <Badge key={i} variant="secondary">
              {s}
            </Badge>
          ))}
        </div>
      );
    }

    // object[] -> auto table
    if (isUniformObjectArray(value)) {
      const keys = Array.from(new Set(value.flatMap((o) => Object.keys(o))));
      return (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-muted/50">
                {keys.map((k) => (
                  <th key={k} className="text-left p-2 font-semibold text-muted-foreground capitalize">
                    {k.replace(/_/g, " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {value.map((row, i) => (
                <tr key={i} className="border-t">
                  {keys.map((k) => (
                    <td key={k} className="p-2 text-foreground">
                      {typeof row[k] === "string" || typeof row[k] === "number"
                        ? String(row[k])
                        : row[k] == null
                        ? ""
                        : String(row[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    // mixed array fallback
    return (
      <ul className="list-disc list-inside space-y-1 text-sm">
        {value.map((item, i) => (
          <li key={i}>{renderValue(item)}</li>
        ))}
      </ul>
    );
  }

  if (typeof value === "object" && value !== null) {
    const obj = value as Record<string, unknown>;

    // Small flat object -> inline key-value badges
    if (isStringRecord(obj) && Object.keys(obj).length <= 8) {
      return <KeyValueBadges data={obj} />;
    }

    // Nested object -> definition list
    return (
      <dl className="space-y-3">
        {Object.entries(obj).map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs font-semibold text-muted-foreground capitalize mb-1">
              {k.replace(/_/g, " ")}
            </dt>
            <dd className="text-sm ml-2">{renderValue(v)}</dd>
          </div>
        ))}
      </dl>
    );
  }

  // Ultimate fallback
  return <span>{String(value)}</span>;
}

// ── Components ───────────────────────────────────────────────────────

export function SafeValue({ value }: { value: unknown }) {
  return <>{renderValue(value)}</>;
}

export function KeyValueBadges({ data }: { data: Record<string, string> }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(data).map(([k, v]) => (
        <Badge key={k} variant="outline" className="text-xs">
          {k} {v}
        </Badge>
      ))}
    </div>
  );
}
