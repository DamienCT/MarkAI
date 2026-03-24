"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Building2,
  CheckSquare,
  FileText,
  Clock,
  Activity,
  ArrowRight,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatRelativeTime, statusColor } from "@/lib/utils";
import type { DashboardStats, AgentRun, CalendarItem } from "@/types";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentRuns, setRecentRuns] = useState<AgentRun[]>([]);
  const [upcomingPosts, setUpcomingPosts] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchDashboard() {
      try {
        const [dashData, runsData, postsData] = await Promise.allSettled([
          api.get<DashboardStats>("/api/v1/dashboard/stats"),
          api.get<AgentRun[]>("/api/v1/agents/runs", { limit: 10 }),
          api.get<CalendarItem[]>("/api/v1/content/calendar/upcoming", { limit: 10 }),
        ]);

        if (dashData.status === "fulfilled") setStats(dashData.value);
        if (runsData.status === "fulfilled") setRecentRuns(runsData.value);
        if (postsData.status === "fulfilled") setUpcomingPosts(postsData.value);
      } catch (err) {
        setError("Failed to load dashboard data");
      } finally {
        setLoading(false);
      }
    }
    fetchDashboard();
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Mission Control</h1>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <p className="text-lg text-muted-foreground">{error}</p>
          <p className="text-sm text-muted-foreground mt-1">Make sure the API backend is running.</p>
        </div>
      </div>
    );
  }

  const statCards = [
    {
      title: "Active Brands",
      value: stats?.active_brands ?? 0,
      icon: Building2,
      href: "/brands",
    },
    {
      title: "Pending Approvals",
      value: stats?.pending_approvals ?? 0,
      icon: CheckSquare,
      href: "/approvals",
    },
    {
      title: "Content in Pipeline",
      value: stats?.content_in_pipeline ?? 0,
      icon: FileText,
      href: "/content",
    },
    {
      title: "Scheduled Posts",
      value: stats?.scheduled_posts ?? 0,
      icon: Clock,
      href: "/content/calendar",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Mission Control</h1>
        <Badge variant="outline" className="text-sm">
          Published this week: {stats?.published_this_week ?? 0}
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Link key={stat.title} href={stat.href}>
            <Card className="hover:shadow-md transition-shadow cursor-pointer">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardDescription>{stat.title}</CardDescription>
                <stat.icon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{stat.value}</div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-lg">Recent Agent Runs</CardTitle>
              <CardDescription>Latest AI agent activity</CardDescription>
            </div>
            <Link href="/system" className="text-sm text-primary hover:underline flex items-center gap-1">
              View all <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {recentRuns.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No recent agent runs
              </p>
            ) : (
              <div className="space-y-3">
                {recentRuns.map((run) => (
                  <div key={run.id} className="flex items-center justify-between rounded-md border p-3">
                    <div className="flex items-center gap-3">
                      <Activity className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">{run.agent_type}</p>
                        <p className="text-xs text-muted-foreground">
                          {run.created_at ? formatRelativeTime(run.created_at) : ""}
                        </p>
                      </div>
                    </div>
                    <Badge className={statusColor(run.status)} variant="outline">
                      {run.status}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-lg">Upcoming Scheduled Posts</CardTitle>
              <CardDescription>Content ready to publish</CardDescription>
            </div>
            <Link href="/content/calendar" className="text-sm text-primary hover:underline flex items-center gap-1">
              View calendar <ArrowRight className="h-3 w-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {upcomingPosts.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No upcoming scheduled posts
              </p>
            ) : (
              <div className="space-y-3">
                {upcomingPosts.map((post) => (
                  <div key={post.id} className="flex items-center justify-between rounded-md border p-3">
                    <div className="flex items-center gap-3">
                      <Clock className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">{post.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {post.platform} {post.brand_name ? `- ${post.brand_name}` : ""}
                        </p>
                      </div>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {post.scheduled_at ? formatRelativeTime(post.scheduled_at) : ""}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
