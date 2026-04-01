"use client";

import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ServiceHealth } from "@/components/system/ServiceHealth";
import { WorkflowMonitor } from "@/components/system/WorkflowMonitor";
import { QueueDepth } from "@/components/system/QueueDepth";
import { api } from "@/lib/api";
import { statusColor } from "@/lib/utils";
import type { ServiceStatus, AgentRun, SchedulerJob, QueueInfo, Brand } from "@/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Activity, ChevronDown, ChevronRight, Play } from "lucide-react";
import { formatRelativeTime } from "@/lib/utils";
import { useRequireRole } from "@/lib/hooks";

const WORKFLOW_TYPES = [
  "content_generation",
  "content_adaptation",
  "engagement_analysis",
  "trend_analysis",
  "performance_report",
] as const;

export default function SystemPage() {
  const { hasAccess, loading: roleLoading } = useRequireRole("admin");
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [jobs, setJobs] = useState<SchedulerJob[]>([]);
  const [queues, setQueues] = useState<QueueInfo[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(true);

  // Filters for Agent Runs table
  const [filterBrand, setFilterBrand] = useState<string>("all");
  const [filterAgentType, setFilterAgentType] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  useEffect(() => {
    async function fetchAll() {
      try {
        const [svcData, runsData, jobsData, queueData, brandsData] = await Promise.allSettled([
          api.get<ServiceStatus[]>("/api/v1/system/services"),
          api.get<AgentRun[]>("/api/v1/agents/runs", { limit: 50 }),
          api.get<SchedulerJob[]>("/api/v1/system/scheduler/jobs"),
          api.get<QueueInfo[]>("/api/v1/system/queues"),
          api.get<Brand[]>("/api/v1/brands"),
        ]);
        if (svcData.status === "fulfilled") setServices(svcData.value);
        if (runsData.status === "fulfilled") setRuns(runsData.value);
        if (jobsData.status === "fulfilled") setJobs(jobsData.value);
        if (queueData.status === "fulfilled") setQueues(queueData.value);
        if (brandsData.status === "fulfilled") setBrands(brandsData.value);
      } catch {
        toast.error("Failed to load system data");
      } finally {
        setLoading(false);
      }
    }
    fetchAll();
  }, []);

  const brandNameMap = brands.reduce<Record<string, string>>((acc, b) => {
    acc[b.id] = b.name;
    return acc;
  }, {});

  // Workflow summary counts
  const runningCount = runs.filter((r) => r.status === "running" || r.status === "pending").length;
  const completedCount = runs.filter((r) => r.status === "completed").length;
  const failedCount = runs.filter((r) => r.status === "failed").length;

  // Per-brand breakdown
  const brandBreakdown = runs.reduce<Record<string, { running: number; completed: number; failed: number }>>((acc, r) => {
    const key = r.brand_id || "unassigned";
    if (!acc[key]) acc[key] = { running: 0, completed: 0, failed: 0 };
    if (r.status === "running" || r.status === "pending") acc[key].running++;
    else if (r.status === "completed") acc[key].completed++;
    else if (r.status === "failed") acc[key].failed++;
    return acc;
  }, {});

  // Filtered runs
  const filteredRuns = runs.filter((r) => {
    if (filterBrand !== "all" && r.brand_id !== filterBrand) return false;
    if (filterAgentType !== "all" && r.agent_type !== filterAgentType) return false;
    if (filterStatus !== "all" && r.status !== filterStatus) return false;
    return true;
  });

  const uniqueAgentTypes = Array.from(new Set(runs.map((r) => r.agent_type)));

  const handleTriggerWorkflow = async (workflowType: string, brandId: string) => {
    try {
      await api.post("/api/v1/agents/trigger", {
        agent_type: workflowType,
        brand_id: brandId,
      });
      toast.success(`Triggered ${workflowType} for ${brandNameMap[brandId] || brandId}`);
      // Refresh runs
      const updatedRuns = await api.get<AgentRun[]>("/api/v1/agents/runs", { limit: 50 });
      setRuns(updatedRuns);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to trigger workflow";
      toast.error(detail);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">System Health</h1>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">System Health</h1>
        <p className="text-muted-foreground">Service status, workflows, and infrastructure</p>
      </div>

      {/* Active Workflows Summary */}
      <Card>
        <CardHeader>
          <CardTitle>Active Workflows</CardTitle>
          <CardDescription>Overview of running, completed, and failed workflows</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3 mb-6">
            <div className="flex items-center gap-3 rounded-md border p-4">
              <div className="h-3 w-3 rounded-full bg-blue-500" />
              <div>
                <p className="text-3xl font-bold">{runningCount}</p>
                <p className="text-xs text-muted-foreground">Running / Pending</p>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-md border p-4">
              <div className="h-3 w-3 rounded-full bg-green-500" />
              <div>
                <p className="text-3xl font-bold">{completedCount}</p>
                <p className="text-xs text-muted-foreground">Completed</p>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-md border p-4">
              <div className="h-3 w-3 rounded-full bg-red-500" />
              <div>
                <p className="text-3xl font-bold">{failedCount}</p>
                <p className="text-xs text-muted-foreground">Failed</p>
              </div>
            </div>
          </div>
          {Object.keys(brandBreakdown).length > 0 && (
            <div>
              <p className="text-sm font-medium mb-2">Per-Brand Breakdown</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(brandBreakdown).map(([brandId, counts]) => (
                  <div key={brandId} className="flex items-center justify-between rounded-md border p-3 text-sm">
                    <span className="font-medium truncate">
                      {brandId === "unassigned" ? "Unassigned" : brandNameMap[brandId] || brandId.slice(0, 8)}
                    </span>
                    <div className="flex gap-3 text-xs text-muted-foreground">
                      <span className="text-blue-600 dark:text-blue-400">{counts.running} active</span>
                      <span className="text-green-600 dark:text-green-400">{counts.completed} done</span>
                      <span className="text-red-600 dark:text-red-400">{counts.failed} err</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Agent Runs Table with Filters */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <CardTitle>Agent Runs</CardTitle>
              <CardDescription>Recent agent runs and workflow executions</CardDescription>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <Select value={filterBrand} onValueChange={setFilterBrand}>
                <SelectTrigger className="w-[160px] h-8 text-xs">
                  <SelectValue placeholder="Brand" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Brands</SelectItem>
                  {brands.map((b) => (
                    <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={filterAgentType} onValueChange={setFilterAgentType}>
                <SelectTrigger className="w-[180px] h-8 text-xs">
                  <SelectValue placeholder="Agent Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  {uniqueAgentTypes.map((t) => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={filterStatus} onValueChange={setFilterStatus}>
                <SelectTrigger className="w-[140px] h-8 text-xs">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Statuses</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="running">Running</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filteredRuns.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No matching workflow runs</p>
          ) : (
            <div className="space-y-2 max-h-[500px] overflow-y-auto">
              {filteredRuns.map((run) => (
                <div key={run.id}>
                  <div className="flex items-center justify-between rounded-md border p-3">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
                        className="text-muted-foreground hover:text-foreground transition-colors"
                      >
                        {expandedRunId === run.id ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </button>
                      <Activity className="h-4 w-4 text-muted-foreground shrink-0" />
                      <div>
                        <p className="text-sm font-medium">{run.agent_type}</p>
                        <p className="text-xs text-muted-foreground">
                          {run.brand_id ? (brandNameMap[run.brand_id] || run.brand_id.slice(0, 8)) : "No brand"}
                          {" - "}
                          {run.started_at ? formatRelativeTime(run.started_at) : formatRelativeTime(run.created_at)}
                          {run.duration_ms !== undefined && run.duration_ms !== null && (
                            <span> - {((run.duration_ms / 1000).toFixed(1))}s</span>
                          )}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {run.error_message && (
                        <span className="text-xs text-destructive max-w-[200px] truncate" title={run.error_message}>
                          {run.error_message}
                        </span>
                      )}
                      <Badge className={statusColor(run.status)} variant="outline">
                        {run.status}
                      </Badge>
                    </div>
                  </div>
                  {expandedRunId === run.id && (
                    <div className="ml-12 mt-1 mb-2 rounded-md border bg-muted/50 p-3">
                      <p className="text-xs font-medium mb-1">Output</p>
                      {run.output_payload ? (
                        <pre className="text-xs text-muted-foreground whitespace-pre-wrap overflow-x-auto max-h-[200px] overflow-y-auto">
                          {JSON.stringify(run.output_payload, null, 2)}
                        </pre>
                      ) : (
                        <p className="text-xs text-muted-foreground">No output data available</p>
                      )}
                      {run.error_message && (
                        <>
                          <p className="text-xs font-medium mt-2 mb-1 text-destructive">Error</p>
                          <p className="text-xs text-destructive">{run.error_message}</p>
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Trigger Workflows */}
      {brands.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Trigger Workflows</CardTitle>
            <CardDescription>Manually trigger agent workflows per brand</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Brand</TableHead>
                    {WORKFLOW_TYPES.map((wf) => (
                      <TableHead key={wf} className="text-center text-xs">{wf.replace(/_/g, " ")}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {brands.filter((b) => b.is_active).map((brand) => (
                    <TableRow key={brand.id}>
                      <TableCell className="font-medium">{brand.name}</TableCell>
                      {WORKFLOW_TYPES.map((wf) => (
                        <TableCell key={wf} className="text-center">
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-8 w-8"
                            onClick={() => handleTriggerWorkflow(wf, brand.id)}
                            title={`Trigger ${wf} for ${brand.name}`}
                          >
                            <Play className="h-3 w-3" />
                          </Button>
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Scheduler Jobs */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Scheduler Jobs</CardTitle>
            <CardDescription>Configured scheduled tasks</CardDescription>
          </CardHeader>
          <CardContent>
            {jobs.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">No scheduler jobs configured</p>
            ) : (
              <div className="space-y-2">
                {jobs.map((job) => (
                  <div key={job.id} className="flex items-center justify-between rounded-md border p-3">
                    <div>
                      <p className="text-sm font-medium">{job.name}</p>
                      <p className="text-xs text-muted-foreground">Schedule: {job.schedule}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-muted-foreground">
                        Runs: {job.run_count} | Next: {job.next_run || "N/A"}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Service Health */}
        <Card>
          <CardHeader>
            <CardTitle>Service Status</CardTitle>
            <CardDescription>Backend service health checks</CardDescription>
          </CardHeader>
          <CardContent>
            <ServiceHealth services={services} />
          </CardContent>
        </Card>

        {/* Queue Depth */}
        <Card>
          <CardHeader>
            <CardTitle>Queue Depths</CardTitle>
            <CardDescription>NATS message queue status</CardDescription>
          </CardHeader>
          <CardContent>
            <QueueDepth queues={queues} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
