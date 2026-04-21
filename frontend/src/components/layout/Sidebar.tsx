"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Building2,
  FileText,
  Calendar,
  CalendarHeart,
  CheckSquare,
  Search,
  BarChart3,
  Brain,
  Terminal,
  Server,
  Settings,
  ChevronLeft,
  ChevronRight,
  Shield,
  Users,
  Cpu,
  FlaskConical,
  Image as ImageIcon,
  Menu,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { BrandSwitcher } from "./BrandSwitcher";
import { Button } from "@/components/ui/button";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard, exact: true },
  { name: "Brands", href: "/brands", icon: Building2 },
  { name: "Content Studio", href: "/content", icon: FileText, exact: true },
  { name: "Calendar", href: "/content/calendar", icon: Calendar },
  { name: "Events", href: "/events", icon: CalendarHeart },
  { name: "Approvals", href: "/approvals", icon: CheckSquare },
  { name: "Intelligence", href: "/intelligence", icon: Search, exact: true },
  { name: "Analytics", href: "/analytics", icon: BarChart3 },
  { name: "Learning", href: "/learning", icon: Brain },
  { name: "AI Providers", href: "/providers", icon: Cpu },
  { name: "Prompt Lab", href: "/prompts", icon: FlaskConical },
  { name: "Product Images", href: "/intelligence/products", icon: ImageIcon },
  { name: "System", href: "/system", icon: Server, exact: true },
  { name: "Audit Log", href: "/system/audit", icon: Shield },
  { name: "Settings", href: "/settings", icon: Settings, exact: true },
  { name: "Users", href: "/settings/users", icon: Users },
];

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
}: {
  collapsed: boolean;
  pathname: string;
  onNavClick?: () => void;
}) {
  return (
    <>
      {!collapsed && (
        <div className="px-3 py-3 border-b">
          <BrandSwitcher />
        </div>
      )}

      <nav className="flex-1 overflow-y-auto py-2">
        {navigation.map((item) => {
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

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

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
            <SidebarContent collapsed={false} pathname={pathname} onNavClick={() => setMobileOpen(false)} />
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
        <SidebarContent collapsed={collapsed} pathname={pathname} />
      </div>
    </>
  );
}
