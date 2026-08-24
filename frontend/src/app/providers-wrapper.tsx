"use client";

import React from "react";
import { SessionProvider, useSession, signIn, signOut } from "next-auth/react";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { PublishingPausedBanner } from "@/components/layout/PublishingPausedBanner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePostWatchToaster } from "@/lib/post-watch";
import { useNotificationToaster } from "@/lib/notification-toaster";

/** Renders nothing — exists only to mount the global toaster hooks once
 * inside the authenticated shell so they survive route changes. */
function GlobalToasters() {
  usePostWatchToaster();
  useNotificationToaster();
  return null;
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();

  React.useEffect(() => {
    if (status === "authenticated" && session?.error === "RefreshAccessTokenError") {
      void signOut({ redirect: false }).then(() => {
        void signIn("azure-ad", { callbackUrl: "/" });
      });
    }
  }, [session?.error, status]);

  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center">
        <Skeleton className="h-32 w-64" />
      </div>
    );
  }

  if (!session || session.error === "RefreshAccessTokenError") {
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
          <GlobalToasters />
          <div className="flex h-screen overflow-hidden">
            <Sidebar />
            <div className="flex flex-1 flex-col overflow-hidden">
              <Header />
              <PublishingPausedBanner />
              <main className="flex-1 overflow-y-auto p-4 md:p-6"><div className="max-w-[1600px] mx-auto">{children}</div></main>
            </div>
          </div>
          <Toaster position="top-right" richColors closeButton />
        </AuthGate>
      </ThemeProvider>
    </SessionProvider>
  );
}
