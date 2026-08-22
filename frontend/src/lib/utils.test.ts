import { describe, expect, it } from "vitest";
import {
  cn,
  formatDate,
  formatDateTime,
  formatRelativeTime,
  platformIcon,
  sanitizeImageUrl,
  statusColor,
  toApiDatetime,
} from "@/lib/utils";

const FALLBACK_BADGE = "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";

describe("statusColor", () => {
  it("maps known statuses to their badge classes", () => {
    expect(statusColor("active")).toContain("bg-green-100");
    expect(statusColor("in_review")).toContain("bg-amber-100");
    expect(statusColor("failed")).toContain("bg-red-100");
    expect(statusColor("published")).toContain("bg-teal-100");
    expect(statusColor("paused_for_review")).toContain("bg-amber-100");
  });

  it("is case-insensitive", () => {
    expect(statusColor("ACTIVE")).toBe(statusColor("active"));
    expect(statusColor("In_Review")).toBe(statusColor("in_review"));
  });

  it("falls back to the neutral badge for unknown or empty statuses", () => {
    expect(statusColor("definitely_not_a_status")).toBe(FALLBACK_BADGE);
    expect(statusColor("")).toBe(FALLBACK_BADGE);
  });

  it("always pairs a light and dark background", () => {
    for (const status of ["active", "queued", "rendering", "down", "archived"]) {
      const classes = statusColor(status);
      expect(classes).toMatch(/(^| )bg-/);
      expect(classes).toMatch(/dark:bg-/);
    }
  });
});

describe("sanitizeImageUrl", () => {
  it("rejects active-content schemes", () => {
    expect(sanitizeImageUrl("javascript:alert(1)")).toBe("");
    expect(sanitizeImageUrl("JaVaScRiPt:alert(1)")).toBe("");
    expect(sanitizeImageUrl("vbscript:msgbox(1)")).toBe("");
    expect(sanitizeImageUrl("data:text/html,<script>alert(1)</script>")).toBe("");
  });

  it("rejects data: SVG payloads (scripts run when embedded)", () => {
    expect(sanitizeImageUrl("data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=")).toBe("");
    expect(sanitizeImageUrl("data:image/svg+xml,<svg onload=alert(1)/>")).toBe("");
  });

  it("allows base64 raster data: URIs only", () => {
    const png = "data:image/png;base64,iVBORw0KGgo=";
    expect(sanitizeImageUrl(png)).toBe(png);
    const webp = "data:image/webp;base64,UklGRg==";
    expect(sanitizeImageUrl(webp)).toBe(webp);
    // Non-base64 raster payloads are excluded too
    expect(sanitizeImageUrl("data:image/png,rawbytes")).toBe("");
  });

  it("allows http(s), absolute, and relative paths", () => {
    expect(sanitizeImageUrl("https://cdn.example.com/a.png")).toBe("https://cdn.example.com/a.png");
    expect(sanitizeImageUrl("http://cdn.example.com/a.png")).toBe("http://cdn.example.com/a.png");
    expect(sanitizeImageUrl("/api/media/v1/files/a.png")).toBe("/api/media/v1/files/a.png");
    expect(sanitizeImageUrl("images/a.png")).toBe("images/a.png");
  });

  it("rejects unknown schemes and empty input", () => {
    expect(sanitizeImageUrl("ftp://example.com/a.png")).toBe("");
    expect(sanitizeImageUrl("")).toBe("");
  });
});

describe("date helpers", () => {
  it("formatDate renders a parseable ISO date", () => {
    expect(formatDate("2026-03-05T10:00:00")).toBe("Mar 5, 2026");
  });

  it("formatDateTime renders date and time", () => {
    expect(formatDateTime("2026-03-05T14:30:00")).toBe("Mar 5, 2026 2:30 PM");
  });

  it("formatRelativeTime renders a suffixed distance", () => {
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(oneHourAgo)).toMatch(/ago$/);
  });

  it("all three return unparseable input unchanged", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
    expect(formatRelativeTime("not-a-date")).toBe("not-a-date");
  });
});

describe("toApiDatetime", () => {
  it("returns empty string for empty or invalid input", () => {
    expect(toApiDatetime("")).toBe("");
    expect(toApiDatetime("garbage")).toBe("");
  });

  it("converts a datetime-local value to an ISO UTC string", () => {
    const result = toApiDatetime("2026-08-20T09:00");
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$/);
    // Round-trips to the same instant the browser would parse locally
    expect(new Date(result).getTime()).toBe(new Date("2026-08-20T09:00").getTime());
  });
});

describe("cn", () => {
  it("merges conditional classes and lets tailwind-merge dedupe", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-sm", false && "hidden", "font-bold")).toBe("text-sm font-bold");
  });
});

describe("platformIcon", () => {
  it("maps known platforms case-insensitively", () => {
    expect(platformIcon("instagram")).toBe("Instagram");
    expect(platformIcon("TikTok")).toBe("Music2");
    expect(platformIcon("x")).toBe("Twitter");
  });

  it("falls back to Globe for unknown platforms", () => {
    expect(platformIcon("myspace")).toBe("Globe");
  });
});
