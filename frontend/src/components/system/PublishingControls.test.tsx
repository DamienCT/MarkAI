import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), put: vi.fn() },
  isAuthError: () => false,
}));

import { api } from "@/lib/api";
import {
  PublishingControls,
  parseScopeKey,
} from "@/components/system/PublishingControls";
import type { Brand, KillSwitchState } from "@/types";

const BRAND_ID = "44fff7ab-2cb2-4745-9af3-7b4ae51f6bf5";
const BRANDS = [{ id: BRAND_ID, name: "Naturespan" } as unknown as Brand];

describe("parseScopeKey", () => {
  const names = { [BRAND_ID]: "Naturespan" };

  it("decodes a brand scope to its name and PUT payload", () => {
    const { label, scope } = parseScopeKey(
      `publishing_enabled:brand:${BRAND_ID}`,
      names
    );
    expect(label).toBe("Brand: Naturespan");
    expect(scope).toEqual({ brand_id: BRAND_ID });
  });

  it("falls back to a uuid prefix for unknown brands", () => {
    const { label } = parseScopeKey(
      "publishing_enabled:brand:aaaaaaaa-0000-0000-0000-000000000000",
      names
    );
    expect(label).toBe("Brand: aaaaaaaa");
  });

  it("decodes a channel scope with its display name", () => {
    const { label, scope } = parseScopeKey(
      "publishing_enabled:channel:website_blog",
      names
    );
    expect(label).toBe("Channel: Website / Blog");
    expect(scope).toEqual({ channel: "website_blog" });
  });

  it("passes an unrecognised key through verbatim with an empty scope", () => {
    const { label, scope } = parseScopeKey("publishing_enabled", names);
    expect(label).toBe("publishing_enabled");
    expect(scope).toEqual({});
  });
});

describe("PublishingControls", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("renders the paused global state with its scoped pauses", async () => {
    const state: KillSwitchState = {
      enabled: false,
      updated_by: "admin@test",
      updated_at: new Date().toISOString(),
      scoped: [
        {
          key: `publishing_enabled:brand:${BRAND_ID}`,
          enabled: false,
          updated_by: "admin@test",
          updated_at: null,
        },
        // enabled scoped flags are informational no-ops — not listed
        {
          key: "publishing_enabled:channel:x",
          enabled: true,
          updated_by: null,
          updated_at: null,
        },
      ],
    };
    vi.mocked(api.get).mockResolvedValue(state);

    render(<PublishingControls brands={BRANDS} />);

    expect(await screen.findByText("paused")).toBeInTheDocument();
    expect(screen.getByText("Brand: Naturespan")).toBeInTheDocument();
    expect(screen.queryByText(/Channel: X/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("renders the enabled state with no scoped rows", async () => {
    vi.mocked(api.get).mockResolvedValue({
      enabled: true,
      updated_by: null,
      updated_at: null,
      scoped: [],
    } satisfies KillSwitchState);

    render(<PublishingControls brands={BRANDS} />);

    expect(await screen.findByText("enabled")).toBeInTheDocument();
    expect(
      screen.getByText("No brand or channel is individually paused.")
    ).toBeInTheDocument();
  });
});
