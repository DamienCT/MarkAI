"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ServiceHealth } from "@/components/system/ServiceHealth";
import { WorkflowMonitor } from "@/components/system/WorkflowMonitor";
import { QueueDepth } from "@/components/system/QueueDepth";
import { api } from "@/lib/api";
import type { ServiceStatus, AgentRun, SchedulerJob, QueueInfo } from "@/types";

export default function SystemPage() {
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [jobs, setJobs] = useState<SchedulerJob[]>([]);
  const [queues, setQueues] = useState<QueueInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchSystem() {
      try {
        const [svcData, runsData, jobsData, queueData] = await Promise.allSettled([
          api.get<ServiceStatus[]>("/api/v1/system/services"),
          api.get<AgentRun[]>("/api/v1/agents/runs", { limit: 20 }),
          api.get<SchedulerJob[]>("/api/v1/system/scheduler/jobs"),
          api.get<QueueInfo[]>("/api/v1/system/queues"),
        ]);
        if (svcData.status === "fulfilled") setServices(svcData.value);
        if (runsData.status === "fulfilled") setRuns(runsData.value);
        if (jobsData.status === "fulfilled") setJobs(jobsData.value);
        if (queueData.status === "fulfilled") setQueues(queueData.value);
      } catch {
        // Handle error
      } finally {
        setLoading(false);
      }
    }
    fetchSystem();
  }, []);

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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Service Status</CardTitle>
            <CardDescription>Backend service health checks</CardDescription>
          </CardHeader>
          <CardContent>
            <ServiceHealth services={services} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Queue Depths</CardTitle>
            <CardDescription>NATS message queue status</CardDescription>
          </CardHeader>
          <CardContent>
            <QueueDepth queues={queues} />
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Workflow Monitor</CardTitle>
            <CardDescription>Recent agent runs and workflow executions</CardDescription>
          </CardHeader>
          <CardContent>
            <WorkflowMonitor runs={runs} />
          </CardContent>
        </Card>

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
      </div>
    </div>
  );
}
