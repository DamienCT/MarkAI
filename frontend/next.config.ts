import type { NextConfig } from "next";

const PHASE_PRODUCTION_BUILD = "phase-production-build";

// Server-side runtime env required by NextAuth (P0-12 / N-19). Validated at
// production build time so a misconfigured deploy fails the build with a
// nonzero exit instead of shipping an app that 500s on every sign-in.
const REQUIRED_RUNTIME_ENV = [
  "AZURE_AD_TENANT_ID",
  "AZURE_AD_CLIENT_ID",
  "AZURE_AD_CLIENT_SECRET",
  "NEXTAUTH_SECRET",
] as const;

function validateRuntimeEnv(): void {
  const problems: string[] = [];
  const missing = REQUIRED_RUNTIME_ENV.filter((name) => !process.env[name]);
  if (missing.length > 0) {
    problems.push(`missing required env vars: ${missing.join(", ")}`);
  }
  const secret = process.env.NEXTAUTH_SECRET;
  if (secret && secret.length < 32) {
    problems.push("NEXTAUTH_SECRET is shorter than 32 characters");
  }
  if (problems.length === 0) return;
  if (process.env.NEXT_BUILD_ALLOW_MISSING_RUNTIME_ENV === "1") {
    // Image builds (frontend/Dockerfile) run without runtime secrets — they
    // are injected at container start, where src/lib/auth.ts fails closed.
    console.warn(
      `[next.config] WARNING: ${problems.join("; ")} — build continues because ` +
        "NEXT_BUILD_ALLOW_MISSING_RUNTIME_ENV=1; the server will refuse to run " +
        "without these at runtime."
    );
    return;
  }
  throw new Error(
    `[next.config] FATAL: ${problems.join("; ")}. Generate secrets with ` +
      "`openssl rand -hex 32`. Set NEXT_BUILD_ALLOW_MISSING_RUNTIME_ENV=1 only " +
      "for image builds that inject these at container start."
  );
}

// Backend origin for the report-only CSP below — same build-time env var the
// client api uses (src/lib/api.ts).
function backendOrigin(): string {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").origin;
  } catch {
    return "http://localhost:8000";
  }
}

// Report-only CSP baseline (FE-06): browsers log violations to the console
// without blocking anything. Enforcement (renaming the header to
// Content-Security-Policy, tightening the unsafe-* script allowances) graduates
// only after a review period of the violation reports.
const CSP_REPORT_ONLY = [
  "default-src 'self'",
  // Next.js currently requires unsafe-inline/unsafe-eval for its runtime.
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  // Media proxy + logo/render previews use blob:/data: plus the backend origin.
  `img-src 'self' blob: data: ${backendOrigin()}`,
  `media-src 'self' blob: data: ${backendOrigin()}`,
  "font-src 'self' data:",
  `connect-src 'self' ${backendOrigin()}`,
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.hstgr.cloud",
      },
      {
        protocol: "http",
        hostname: "localhost",
        port: "8000",
      },
      {
        protocol: "http",
        hostname: "minio",
        port: "9000",
      },
    ],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Content-Security-Policy-Report-Only", value: CSP_REPORT_ONLY },
        ],
      },
    ];
  },
};

export default function config(phase: string): NextConfig {
  if (phase === PHASE_PRODUCTION_BUILD) {
    validateRuntimeEnv();
  }
  return nextConfig;
}
