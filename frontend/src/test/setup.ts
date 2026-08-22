// Vitest setup — runs before every test file (see vitest.config.ts).
// Registers the jest-dom matchers on Vitest's expect and cleans up the DOM
// between tests (auto-cleanup only happens when Vitest globals are enabled,
// and we keep explicit imports instead).
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
