import { describe, expect, it } from "vitest";
import {
  ALL_CHANNELS,
  CHANNEL_CONFIG_FIELDS,
  CHANNEL_DISPLAY_NAMES,
} from "@/types";

// CHANNEL_CONFIG_FIELDS is the frontend half of the backend credential
// contract (brand_guidelines.channels.<channel>.<field>) — these tests guard
// the invariants TypeScript cannot: ALL_CHANNELS staying in sync with the
// Record keys, and field definitions staying well-formed.

describe("channel contract", () => {
  it("ALL_CHANNELS has no duplicates", () => {
    expect(new Set(ALL_CHANNELS).size).toBe(ALL_CHANNELS.length);
  });

  it("ALL_CHANNELS covers every configured channel exactly", () => {
    expect([...ALL_CHANNELS].sort()).toEqual(Object.keys(CHANNEL_CONFIG_FIELDS).sort());
    expect([...ALL_CHANNELS].sort()).toEqual(Object.keys(CHANNEL_DISPLAY_NAMES).sort());
  });

  it("every channel defines at least one config field", () => {
    for (const ch of ALL_CHANNELS) {
      expect(CHANNEL_CONFIG_FIELDS[ch].length).toBeGreaterThan(0);
    }
  });

  it("every field has a non-empty key, label, and placeholder", () => {
    for (const ch of ALL_CHANNELS) {
      for (const field of CHANNEL_CONFIG_FIELDS[ch]) {
        expect(field.key).toBeTruthy();
        expect(field.label).toBeTruthy();
        expect(field.placeholder).toBeTruthy();
      }
    }
  });

  it("field keys are unique within each channel", () => {
    for (const ch of ALL_CHANNELS) {
      const keys = CHANNEL_CONFIG_FIELDS[ch].map((f) => f.key);
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it("the optional flag and the '(optional)' label suffix agree", () => {
    for (const ch of ALL_CHANNELS) {
      for (const field of CHANNEL_CONFIG_FIELDS[ch]) {
        expect(Boolean(field.optional)).toBe(field.label.includes("(optional)"));
      }
    }
  });

  it("every channel has a non-empty display name", () => {
    for (const ch of ALL_CHANNELS) {
      expect(CHANNEL_DISPLAY_NAMES[ch]).toBeTruthy();
    }
  });
});
