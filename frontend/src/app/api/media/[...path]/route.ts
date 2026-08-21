/**
 * Same-origin media proxy — the backend's media endpoints now require auth
 * (Entra bearer, X-Media-Token, or a signed URL), but browser <img>/<video>
 * tags cannot send headers. This route checks the NextAuth session, then
 * forwards the request to the backend with the shared MEDIA_PROXY_TOKEN,
 * streaming the response back (Range and conditional headers included so
 * video scrubbing and browser caching keep working).
 *
 * Path allowlist: only `v1/files/...` and `v1/brands/<uuid>/logos/<label>`
 * are proxied — everything else 404s without touching the backend.
 */
import type { NextRequest } from "next/server";
import { getToken } from "next-auth/jwt";

// Server-only runtime env (never NEXT_PUBLIC — the token must not be inlined
// into client bundles). INTERNAL_API_URL points at the backend container;
// NEXT_PUBLIC_API_URL covers local dev where both run on localhost.
const BACKEND_URL =
  process.env.INTERNAL_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://backend:8000";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Only forward these request headers to the backend.
const FORWARD_REQUEST_HEADERS = ["range", "if-none-match", "if-modified-since"];

// Only expose these response headers to the browser.
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "content-length",
  "content-range",
  "accept-ranges",
  "cache-control",
  "etag",
  "last-modified",
  "content-disposition",
  "x-content-type-options",
  "content-security-policy",
];

function isAllowedPath(segments: string[]): boolean {
  if (
    segments.some(
      (s) => !s || s === "." || s === ".." || s.includes("\\")
    )
  ) {
    return false;
  }
  if (segments[0] !== "v1") return false;
  // v1/files/<object path...>
  if (segments[1] === "files" && segments.length >= 3) return true;
  // v1/brands/<uuid>/logos/<label>
  if (
    segments[1] === "brands" &&
    segments.length === 5 &&
    UUID_RE.test(segments[2]) &&
    segments[3] === "logos"
  ) {
    return true;
  }
  return false;
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> }
) {
  // Session gate: any signed-in user may load media (mirrors the API's
  // read access); no session → 401, never a redirect (img tags can't follow
  // a sign-in flow anyway).
  const session = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
  if (!session) {
    return new Response("Unauthorized", { status: 401 });
  }

  // Catch-all params arrive already URL-decoded — validate as-is and
  // re-encode when building the backend URL.
  const { path } = await ctx.params;
  const segments = path || [];
  if (!isAllowedPath(segments)) {
    return new Response("Not found", { status: 404 });
  }

  // Forward transform/cache-bust query params, but never auth-ish ones.
  const search = new URLSearchParams(req.nextUrl.searchParams);
  search.delete("mt");
  search.delete("exp");
  const qs = search.toString();

  const url =
    `${BACKEND_URL}/api/` +
    segments.map(encodeURIComponent).join("/") +
    (qs ? `?${qs}` : "");

  const headers: Record<string, string> = {};
  const mediaToken = process.env.MEDIA_PROXY_TOKEN || "";
  if (mediaToken) headers["X-Media-Token"] = mediaToken;
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers[name] = value;
  }

  let upstream: Response;
  try {
    upstream = await fetch(url, { headers, cache: "no-store" });
  } catch {
    return new Response("Media backend unreachable", { status: 502 });
  }

  const out = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: out,
  });
}
