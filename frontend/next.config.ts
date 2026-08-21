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
