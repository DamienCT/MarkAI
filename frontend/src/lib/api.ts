import { getSession } from "next-auth/react";
import type { Session } from "next-auth";

// NEXT_PUBLIC_API_URL is inlined at build time by Next.js.
const _rawApiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Cache getSession() to avoid redundant /api/auth/session fetches.
// Multiple concurrent api.get() calls share a single in-flight request.
let _sessionPromise: Promise<Session | null> | null = null;
let _sessionCachedAt = 0;
const SESSION_CACHE_MS = 30_000; // 30 seconds — role changes are rare

function getCachedSession(): Promise<Session | null> {
  const now = Date.now();
  if (!_sessionPromise || now - _sessionCachedAt > SESSION_CACHE_MS) {
    _sessionCachedAt = now;
    _sessionPromise = getSession().finally(() => {
      // Allow next call after cache expires to start fresh
      setTimeout(() => { _sessionPromise = null; }, SESSION_CACHE_MS);
    });
  }
  return _sessionPromise;
}

// Force HTTPS: if the inlined URL starts with http:// and contains a real domain
// (not localhost), upgrade it. This catches misconfigured env vars at build time.
export const API_BASE_URL =
  _rawApiUrl.startsWith("http://") && !_rawApiUrl.includes("localhost")
    ? _rawApiUrl.replace("http://", "https://")
    : _rawApiUrl;

interface ApiError {
  detail: string;
  status: number;
}

export interface RequestOptions {
  signal?: AbortSignal;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private async getHeaders(): Promise<HeadersInit> {
    const session = await getCachedSession();
    const headers: HeadersInit = {
      "Content-Type": "application/json",
    };
    if (session?.accessToken) {
      headers["Authorization"] = `Bearer ${session.accessToken}`;
    }
    return headers;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    params?: Record<string, string | number | boolean | undefined>,
    options?: RequestOptions
  ): Promise<T> {
    const headers = await this.getHeaders();
    // Add trailing slash only for collection endpoints (paths ending in a known collection name)
    // Don't add for paths with UUIDs/IDs at the end (path parameter endpoints)
    const needsSlash = !path.endsWith("/") && !path.includes("?") && /\/(brands|content|products|calendar|campaigns|approvals|prompts|users|notifications|settings|agents|intelligence|providers|learning|system|audit|events)\/?$/.test(path);
    const normalizedPath = needsSlash ? path + "/" : path;
    let url = `${this.baseUrl}${normalizedPath}`;

    if (params) {
      const searchParams = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          searchParams.append(key, String(value));
        }
      });
      const qs = searchParams.toString();
      if (qs) url += `?${qs}`;
    }

    const response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: options?.signal,
    });

    if (!response.ok) {
      // On 401, redirect to sign-in (token expired or invalid)
      if (response.status === 401 && typeof window !== "undefined") {
        const { signIn } = await import("next-auth/react");
        signIn("azure-ad");
        return undefined as T;
      }
      const error: ApiError = {
        detail: "An error occurred",
        status: response.status,
      };
      try {
        const data = await response.json();
        error.detail = data.detail || data.message || JSON.stringify(data);
      } catch (parseError) {
        error.detail = response.statusText;
      }
      throw error;
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json();
  }

  async get<T>(
    path: string,
    params?: Record<string, string | number | boolean | undefined>,
    options?: RequestOptions
  ): Promise<T> {
    return this.request<T>("GET", path, undefined, params, options);
  }

  async post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>("POST", path, body, undefined, options);
  }

  async put<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>("PUT", path, body, undefined, options);
  }

  async patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>("PATCH", path, body, undefined, options);
  }

  async delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("DELETE", path, undefined, undefined, options);
  }

  async uploadFile<T>(path: string, file: File, extraFields?: Record<string, string>): Promise<T> {
    const session = await getCachedSession();
    const headers: HeadersInit = {};
    if (session?.accessToken) {
      headers["Authorization"] = `Bearer ${session.accessToken}`;
    }

    const formData = new FormData();
    formData.append("file", file);
    if (extraFields) {
      Object.entries(extraFields).forEach(([key, value]) => {
        formData.append(key, value);
      });
    }

    const url = `${this.baseUrl}${path}`;
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: formData,
    });

    if (!response.ok) {
      const error: ApiError = { detail: "Upload failed", status: response.status };
      try {
        const data = await response.json();
        error.detail = data.detail || data.message || JSON.stringify(data);
      } catch {
        error.detail = response.statusText;
      }
      throw error;
    }

    return response.json();
  }
}

export const api = new ApiClient(API_BASE_URL);

/** Resolve a relative API path (e.g. /api/v1/brands/.../logos/primary) to a full URL */
export function apiUrl(path: string): string {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return `${API_BASE_URL}${path}`;
}

/** Resolve a MinIO object path to a proxied file URL via the backend.
 *  e.g. "products/abc/image.png" → "https://api.../api/v1/files/products/abc/image.png"
 *  Also rewrites legacy presigned URLs (http://minio:9000/bucket/path) to use the proxy.
 */
export function fileUrl(path: string): string {
  if (!path) return "";
  // Rewrite legacy MinIO presigned URLs to proxy through backend
  if (path.includes("minio:9000") || path.includes("minio%3A9000")) {
    // Extract the object path from: http://minio:9000/bucket-name/object/path?signature...
    const match = path.match(/minio:9000\/[^/]+\/(.+?)(\?|$)/);
    if (match) return `${API_BASE_URL}/api/v1/files/${match[1]}`;
  }
  if (path.startsWith("http")) return path;
  if (path.startsWith("/")) return `${API_BASE_URL}${path}`;
  return `${API_BASE_URL}/api/v1/files/${path}`;
}
