"use client";

import React from "react";
import { SessionProvider, useSession, signIn } from "next-auth/react";
import { ThemeProvider } from "next-themes";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * When AZURE_AD_CLIENT_ID is not configured (dev mode), skip auth gating.
 * This env var must be prefixed with NEXT_PUBLIC_ to be available client-side.
 */
const SSO_ENABLED = !!process.env.NEXT_PUBLIC_AZURE_AD_CLIENT_ID;

function AuthGate({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();

  // In dev mode (no Azure AD configured), skip the gate entirely
  if (!SSO_ENABLED) {
    return <>{children}</>;
  }

  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center">
        <Skeleton className="h-32 w-64" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle className="text-3xl font-bold">MARKAI</CardTitle>
            <CardDescription>AI Marketing Platform</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col items-center gap-4">
            <p className="text-sm text-muted-foreground text-center">
              Sign in with your Microsoft account to access the platform.
            </p>
            <Button
              className="w-full"
              size="lg"
              onClick={() => signIn("azure-ad", { callbackUrl: "/" })}
            >
              Sign in with Microsoft
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <>{children}</>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        <AuthGate>
          <div className="flex h-screen overflow-hidden">
            <Sidebar />
            <div className="flex flex-1 flex-col overflow-hidden">
              <Header />
              <main className="flex-1 overflow-y-auto p-6">{children}</main>
            </div>
          </div>
        </AuthGate>
      </ThemeProvider>
    </SessionProvider>
  );
}
