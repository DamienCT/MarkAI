"use client";

import React, { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { BookOpen, CalendarDays, ChevronDown, ChevronUp } from "lucide-react";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// Seasonal accent per month so the 12 cards read as a year at a glance
// (winter blues → spring greens → summer ambers → autumn oranges).
const MONTH_ACCENT: Record<string, string> = {
  January: "border-l-blue-400", February: "border-l-blue-400", March: "border-l-emerald-400",
  April: "border-l-emerald-400", May: "border-l-emerald-400", June: "border-l-amber-400",
  July: "border-l-amber-400", August: "border-l-amber-400", September: "border-l-orange-400",
  October: "border-l-orange-400", November: "border-l-slate-400", December: "border-l-blue-400",
};

interface MonthSection {
  month: string;
  body: string;
}

interface ParsedDoc {
  intro: string;
  months: MonthSection[];
}

/** Split the markdown doc into an intro block + per-month sections.
 *  A heading line (any level) whose text starts with a month name opens a
 *  month section; everything before the first such heading is the intro. */
function parseStrategyDocument(doc: string): ParsedDoc {
  const lines = doc.split("\n");
  const intro: string[] = [];
  const months: MonthSection[] = [];
  let current: MonthSection | null = null;

  const headingRe = /^#{1,4}\s+(.*)$/;
  for (const line of lines) {
    const m = line.match(headingRe);
    const headingText = m?.[1]?.trim() ?? "";
    const matchedMonth = MONTHS.find((mo) =>
      new RegExp(`\\b${mo}\\b`, "i").test(headingText)
    );
    if (m && matchedMonth) {
      if (current) months.push(current);
      current = { month: matchedMonth, body: "" };
      continue;
    }
    if (current) {
      current.body += line + "\n";
    } else {
      intro.push(line);
    }
  }
  if (current) months.push(current);

  // Keep only the first occurrence of each month, in calendar order.
  const seen = new Set<string>();
  const ordered: MonthSection[] = [];
  for (const mo of MONTHS) {
    const found = months.find((s) => s.month === mo && !seen.has(mo));
    if (found) {
      seen.add(mo);
      ordered.push(found);
    }
  }

  return { intro: intro.join("\n").trim(), months: ordered };
}

const PROSE_CLASS =
  "prose prose-sm max-w-none dark:prose-invert prose-headings:text-foreground " +
  "prose-p:text-muted-foreground prose-strong:text-foreground prose-li:text-muted-foreground " +
  "prose-table:text-xs prose-th:bg-muted prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1";

export function ContentCalendarStrategy({ document: doc }: { document: string }) {
  const { intro, months } = useMemo(() => parseStrategyDocument(doc), [doc]);
  const [showRaw, setShowRaw] = useState(false);

  // Fallback: if parsing found no month sections, render the raw markdown so
  // we never hide content just because the heading format was unexpected.
  if (months.length === 0) {
    return (
      <Card className="print-break" id="section-calendar-strategy">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-primary" />
            Strategy Document
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className={PROSE_CLASS}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc}</ReactMarkdown>
          </div>
        </CardContent>
      </Card>
    );
  }

  const slug = (mo: string) => `month-${mo.toLowerCase()}`;

  return (
    <Card className="print-break" id="section-calendar-strategy">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarDays className="h-5 w-5 text-primary" />
          Content Calendar — 12 Month Plan
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          The year broken down month by month. Click a month to jump to its plan.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Timeline chips */}
        <div className="flex flex-wrap gap-1.5 no-print" data-no-print>
          {months.map((s) => (
            <button
              key={s.month}
              type="button"
              onClick={() => {
                const el = window.document.getElementById(slug(s.month));
                el?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              className="rounded-full border px-3 py-1 text-xs font-medium hover:bg-accent transition-colors"
            >
              {s.month.slice(0, 3)}
            </button>
          ))}
        </div>

        {/* Intro / executive narrative before the months */}
        {intro && (
          <div className={`${PROSE_CLASS} rounded-lg border bg-muted/20 p-4`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{intro}</ReactMarkdown>
          </div>
        )}

        {/* Month cards */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {months.map((s, idx) => (
            <div
              key={s.month}
              id={slug(s.month)}
              className={`rounded-lg border border-l-4 ${MONTH_ACCENT[s.month] || "border-l-primary"} p-4 space-y-2 scroll-mt-20`}
            >
              <div className="flex items-center justify-between">
                <h4 className="font-semibold flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold">
                    {idx + 1}
                  </span>
                  {s.month}
                </h4>
                <Badge variant="outline" className="text-[10px]">
                  Month {idx + 1}
                </Badge>
              </div>
              <div className={PROSE_CLASS}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {s.body.trim()}
                </ReactMarkdown>
              </div>
            </div>
          ))}
        </div>

        {/* Raw document toggle */}
        <div className="no-print" data-no-print>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowRaw((v) => !v)}
          >
            {showRaw ? (
              <ChevronUp className="mr-1.5 h-4 w-4" />
            ) : (
              <ChevronDown className="mr-1.5 h-4 w-4" />
            )}
            {showRaw ? "Hide full document" : "View full document"}
          </Button>
          {showRaw && (
            <div className={`${PROSE_CLASS} mt-3 rounded-lg border p-4`}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc}</ReactMarkdown>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
