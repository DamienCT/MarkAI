"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  LayoutDashboard,
  Building2,
  FileText,
  Calendar,
  CalendarHeart,
  Search,
  BarChart3,
  Terminal,
  Server,
  Settings,
  ChevronLeft,
  ChevronRight,
  Shield,
  Users,
  Cpu,
  Menu,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { BrandSwitcher } from "./BrandSwitcher";
import { Button } from "@/components/ui/button";

// `minRole` restricts a menu link to roles at or above the given level.
// Items without minRole are visible to everyone (page-level role checks
// still redirect unauthorized users at click time).
type NavItem = {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
  minRole?: "viewer" | "editor" | "manager" | "admin";
};

const navigation: NavItem[] = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard, exact: true },
  { name: "Brands", href: "/brands", icon: Building2 },
  { name: "Content Studio", href: "/content", icon: FileText, exact: true },
  { name: "Calendar", href: "/content/calendar", icon: Calendar },
  { name: "Events", href: "/events", icon: CalendarHeart },
  { name: "Intelligence", href: "/intelligence", icon: Search, exact: true },
  { name: "Analytics", href: "/analytics", icon: BarChart3 },
  { name: "AI Providers", href: "/providers", icon: Cpu, minRole: "admin" },
  { name: "System", href: "/system", icon: Server, exact: true, minRole: "admin" },
  { name: "Audit Log", href: "/system/audit", icon: Shield, minRole: "admin" },
  { name: "Settings", href: "/settings", icon: Settings, exact: true, minRole: "admin" },
  { name: "Users", href: "/settings/users", icon: Users, minRole: "admin" },
];

const ROLE_LEVELS: Record<string, number> = {
  viewer: 10,
  editor: 60,
  manager: 80,
  admin: 100,
};

function isNavActive(pathname: string, href: string, exact?: boolean): boolean {
  if (exact) {
    return pathname === href;
  }
  // For non-exact, match if pathname starts with href
  // but avoid /content matching /content/calendar (that's handled by exact: true on /content)
  return pathname === href || pathname.startsWith(href + "/");
}

function SidebarContent({
  collapsed,
  pathname,
  onNavClick,
  userLevel,
}: {
  collapsed: boolean;
  pathname: string;
  onNavClick?: () => void;
  userLevel: number;
}) {
  return (
    <>
      {!collapsed && (
        <div className="px-3 py-3 border-b">
          <BrandSwitcher />
        </div>
      )}

      <nav className="flex-1 overflow-y-auto py-2">
        {navigation.filter((item) => {
          if (!item.minRole) return true;
          return userLevel >= ROLE_LEVELS[item.minRole];
        }).map((item) => {
          const active = isNavActive(pathname, item.href, item.exact);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavClick}
              className={cn(
                "flex items-center gap-3 mx-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                collapsed && "justify-center px-2"
              )}
              title={collapsed ? item.name : undefined}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{item.name}</span>}
            </Link>
          );
        })}
      </nav>
    </>
  );
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  const { data: session } = useSession();

  // Current user's role level — used to gate role-restricted menu items.
  // Default to "viewer" when the session is still loading or the role
  // claim is missing, so admin-only links stay hidden by default.
  const userRole =
    (session?.user as Record<string, unknown> | undefined)?.role as string | undefined;
  const userLevel = ROLE_LEVELS[userRole ?? "viewer"] ?? 0;

  // Close mobile drawer on route change — guarded state adjustment during
  // render (react.dev "Storing information from previous renders") instead
  // of a state-sync effect, so no extra commit+render cascade.
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (prevPathname !== pathname) {
    setPrevPathname(pathname);
    setMobileOpen(false);
  }

  return (
    <>
      {/* Mobile hamburger button — fixed top-left, visible only below md */}
      <Button
        variant="ghost"
        size="icon"
        className="fixed top-3 left-3 z-50 md:hidden"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation menu"
      >
        <Menu className="h-5 w-5" />
      </Button>

      {/* Mobile overlay + slide-in drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileOpen(false)}
          />
          {/* Drawer */}
          <div className="absolute inset-y-0 left-0 w-64 flex flex-col bg-card border-r shadow-lg animate-in slide-in-from-left duration-200">
            <div className="flex h-16 items-center justify-between border-b px-4">
              <Link href="/" className="flex items-center gap-2" onClick={() => setMobileOpen(false)}>
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold text-sm">
                  M
                </div>
                <span className="text-lg font-bold">MARKAI</span>
              </Link>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setMobileOpen(false)}
                aria-label="Close navigation menu"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <SidebarContent collapsed={false} pathname={pathname} onNavClick={() => setMobileOpen(false)} userLevel={userLevel} />
          </div>
        </div>
      )}

      {/* Desktop sidebar — hidden below md */}
      <div
        className={cn(
          "hidden md:flex flex-col border-r bg-card transition-all duration-300",
          collapsed ? "w-16" : "w-64"
        )}
      >
        <div className="flex h-16 items-center justify-between border-b px-4">
          {!collapsed && (
            <Link href="/" className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold text-sm">
                M
              </div>
              <span className="text-lg font-bold">MARKAI</span>
            </Link>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setCollapsed(!collapsed)}
            className={cn(collapsed && "mx-auto")}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </Button>
        </div>
        <SidebarContent collapsed={collapsed} pathname={pathname} userLevel={userLevel} />
      </div>
    </>
  );
}
