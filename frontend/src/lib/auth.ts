import type { NextAuthOptions } from "next-auth";
import AzureADProvider from "next-auth/providers/azure-ad";
import type { JWT } from "next-auth/jwt";

const REFRESH_BUFFER_SECONDS = 5 * 60;

// Validate required auth environment variables (P0-12 / N-19).
const REQUIRED_AUTH_ENV = ["AZURE_AD_TENANT_ID", "AZURE_AD_CLIENT_ID", "AZURE_AD_CLIENT_SECRET"] as const;
const missingAuthEnv = REQUIRED_AUTH_ENV.filter((name) => !process.env[name]);
const authEnvProblems: string[] = [];
if (missingAuthEnv.length > 0) {
  authEnvProblems.push(`missing required Azure AD env vars: ${missingAuthEnv.join(", ")}`);
}
if (!process.env.NEXTAUTH_SECRET) {
  authEnvProblems.push("NEXTAUTH_SECRET is not set");
} else if (process.env.NEXTAUTH_SECRET.length < 32) {
  authEnvProblems.push("NEXTAUTH_SECRET is shorter than 32 characters");
}
if (authEnvProblems.length > 0) {
  const message =
    `FATAL: ${authEnvProblems.join("; ")} — NextAuth cannot operate safely. ` +
    "Generate secrets with: openssl rand -hex 32";
  // `next build` imports this module while collecting page data, and image
  // builds legitimately run without runtime secrets (they are injected at
  // container start) — next.config.ts decides whether the BUILD fails.
  // At production runtime the config is unrecoverable: fail closed.
  if (process.env.NODE_ENV === "production" && process.env.NEXT_PHASE !== "phase-production-build") {
    throw new Error(message);
  }
  console.error(message);
}

const TOKEN_ENDPOINT = `https://login.microsoftonline.com/${process.env.AZURE_AD_TENANT_ID}/oauth2/v2.0/token`;

type RefreshResult = JWT & {
  accessToken?: string;
  idToken?: string;
  refreshToken?: string;
  expiresAt?: number;
  error?: string;
};

async function refreshAzureToken(token: JWT): Promise<RefreshResult> {
  if (!token.refreshToken) {
    return {
      ...token,
      error: "RefreshAccessTokenError",
    };
  }

  try {
    const body = new URLSearchParams({
      client_id: process.env.AZURE_AD_CLIENT_ID!,
      client_secret: process.env.AZURE_AD_CLIENT_SECRET!,
      grant_type: "refresh_token",
      refresh_token: token.refreshToken,
      scope: "openid profile email offline_access",
    });

    const response = await fetch(TOKEN_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body,
    });

    const refreshed = await response.json();

    if (!response.ok) {
      throw refreshed;
    }

    return {
      ...token,
      accessToken: refreshed.id_token ?? token.accessToken,
      idToken: refreshed.id_token ?? token.idToken,
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
      expiresAt: Math.floor(Date.now() / 1000) + (refreshed.expires_in ?? 3600),
      error: undefined,
    };
  } catch (error) {
    console.error("Failed to refresh Azure token", error);
    return {
      ...token,
      error: "RefreshAccessTokenError",
    };
  }
}

export const authOptions: NextAuthOptions = {
  providers: [
    AzureADProvider({
      clientId: process.env.AZURE_AD_CLIENT_ID!,
      clientSecret: process.env.AZURE_AD_CLIENT_SECRET!,
      tenantId: process.env.AZURE_AD_TENANT_ID!,
      authorization: {
        params: {
          scope: "openid profile email offline_access",
        },
      },
    }),
  ],
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        // Use the ID token for backend auth (audience = our client ID)
        // NOT the access token (audience = graph.microsoft.com)
        token.accessToken = account.id_token;
        token.idToken = account.id_token;
        token.refreshToken = account.refresh_token;
        token.expiresAt = account.expires_at;
        token.error = undefined;
        // Fetch user role on initial sign-in so it persists in the JWT
        token.role = undefined;
        token.roleFetchedAt = undefined;
      }

      // Fetch role if missing or stale (re-check every 30 minutes — role changes are rare)
      const ROLE_TTL = 30 * 60;
      const now = Math.floor(Date.now() / 1000);
      const roleStale = !token.role || !token.roleFetchedAt || now - (token.roleFetchedAt as number) > ROLE_TTL;
      if (roleStale && token.accessToken) {
        try {
          // This runs server-side (inside the frontend container), so prefer a
          // runtime-only internal URL. NEXT_PUBLIC_* vars are inlined at build
          // time and point at the browser host (localhost), which is unreachable
          // from inside the container — so they can't be used for server fetches.
          const apiUrl =
            process.env.INTERNAL_API_URL ||
            process.env.NEXT_PUBLIC_API_URL ||
            "http://backend:8000";
          const res = await fetch(`${apiUrl}/api/v1/users/me`, {
            headers: { Authorization: `Bearer ${token.accessToken}` },
          });
          if (res.ok) {
            const userData = await res.json();
            token.role = userData.role || "viewer";
            token.roleFetchedAt = now;
          } else if (!token.role) {
            token.role = "viewer";
          }
        } catch {
          if (!token.role) {
            token.role = "viewer";
          }
        }
      }

      if (!token.expiresAt) {
        return token;
      }

      const shouldRefresh = now >= (token.expiresAt as number) - REFRESH_BUFFER_SECONDS;

      if (!shouldRefresh) {
        return token;
      }

      return refreshAzureToken(token);
    },
    async session({ session, token }) {
      return {
        ...session,
        accessToken: token.accessToken as string,
        error: token.error as string | undefined,
        user: {
          ...session.user,
          id: token.sub,
          role: (token.role as string) || "viewer",
        },
      };
    },
  },
  pages: {
    signIn: "/auth/signin",
  },
  session: {
    strategy: "jwt",
    maxAge: 7 * 24 * 60 * 60, // 7 days
  },
  secret: process.env.NEXTAUTH_SECRET,
};
