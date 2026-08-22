import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE_URL, apiUrl, fileUrl } from "@/lib/api";

// api.ts pulls in next-auth/react at module scope for session handling; the
// URL helpers under test never touch it, so stub it out.
vi.mock("next-auth/react", () => ({
  getSession: vi.fn().mockResolvedValue(null),
  signIn: vi.fn(),
}));

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("apiUrl", () => {
  it("returns empty string for empty input", () => {
    expect(apiUrl("")).toBe("");
  });

  it("passes absolute URLs through untouched", () => {
    expect(apiUrl("https://cdn.example.com/a.png")).toBe("https://cdn.example.com/a.png");
  });

  it("rewrites files-proxy paths to the same-origin media proxy", () => {
    expect(apiUrl("/api/v1/files/products/abc/image.png")).toBe(
      "/api/media/v1/files/products/abc/image.png"
    );
  });

  it("rewrites brand logo paths to the media proxy", () => {
    expect(apiUrl("/api/v1/brands/b-123/logos/primary")).toBe(
      "/api/media/v1/brands/b-123/logos/primary"
    );
  });

  it("prefixes non-media API paths with the API base URL", () => {
    expect(apiUrl("/api/v1/content/xyz")).toBe(`${API_BASE_URL}/api/v1/content/xyz`);
  });
});

describe("fileUrl", () => {
  it("returns empty string for empty input", () => {
    expect(fileUrl("")).toBe("");
  });

  it("rewrites legacy MinIO presigned URLs to the media proxy", () => {
    expect(
      fileUrl("http://minio:9000/markai-media/products/abc/image.png?X-Amz-Signature=deadbeef")
    ).toBe("/api/media/v1/files/products/abc/image.png");
  });

  it("rewrites legacy MinIO URLs without a query string", () => {
    expect(fileUrl("http://minio:9000/markai-media/videos/reel.mp4")).toBe(
      "/api/media/v1/files/videos/reel.mp4"
    );
  });

  it("passes non-MinIO absolute URLs through untouched", () => {
    expect(fileUrl("https://cdn.example.com/a.png")).toBe("https://cdn.example.com/a.png");
  });

  it("proxies absolute media API paths", () => {
    expect(fileUrl("/api/v1/files/products/abc/image.png")).toBe(
      "/api/media/v1/files/products/abc/image.png"
    );
    expect(fileUrl("/api/v1/brands/b-123/logos/primary")).toBe(
      "/api/media/v1/brands/b-123/logos/primary"
    );
  });

  it("prefixes non-media absolute API paths with the API base URL", () => {
    expect(fileUrl("/api/v1/content/xyz/download")).toBe(
      `${API_BASE_URL}/api/v1/content/xyz/download`
    );
  });

  it("treats bare object paths as files-proxy keys", () => {
    expect(fileUrl("products/abc/image.png")).toBe(
      "/api/media/v1/files/products/abc/image.png"
    );
  });
});

describe("API_BASE_URL https upgrade", () => {
  it("upgrades http:// to https:// for non-localhost hosts", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://api.example.com");
    const mod = await import("@/lib/api");
    expect(mod.API_BASE_URL).toBe("https://api.example.com");
  });

  it("leaves localhost http:// untouched", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000");
    const mod = await import("@/lib/api");
    expect(mod.API_BASE_URL).toBe("http://localhost:8000");
  });
});
