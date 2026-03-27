import { getSession } from "next-auth/react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
    const session = await getSession();
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
    const needsSlash = !path.endsWith("/") && !path.includes("?") && /\/(brands|content|products|calendar|campaigns|approvals|prompts|users|notifications|settings|agents|intelligence|providers|learning|system|audit)\/?$/.test(path);
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
      // Don't auto-redirect on 401 — the AuthGate handles sign-in state.
      // API 401s are shown as error toasts by each page's catch handler.
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
    const session = await getSession();
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
