"use client";

import React from "react";
import { CheckCircle, AlertTriangle, XCircle } from "lucide-react";
import { cn, statusColor, formatRelativeTime } from "@/lib/utils";
import type { ServiceStatus } from "@/types";

interface ServiceHealthProps {
  services: ServiceStatus[];
}

export function ServiceHealth({ services }: ServiceHealthProps) {
  if (services.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8">
        No service status data available
      </p>
    );
  }

  const iconMap: Record<string, React.ReactNode> = {
    healthy: <CheckCircle className="h-4 w-4 text-green-500" />,
    degraded: <AlertTriangle className="h-4 w-4 text-yellow-500" />,
    down: <XCircle className="h-4 w-4 text-red-500" />,
  };

  return (
    <div className="space-y-2">
      {services.map((service) => (
        <div key={service.name} className="flex items-center justify-between rounded-md border p-3">
          <div className="flex items-center gap-3">
            {iconMap[service.status] || <CheckCircle className="h-4 w-4" />}
            <div>
              <p className="text-sm font-medium">{service.name}</p>
              <p className="text-xs text-muted-foreground">
                Last check: {formatRelativeTime(service.last_check)}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {service.latency_ms !== undefined && (
              <span className="text-xs text-muted-foreground">{service.latency_ms}ms</span>
            )}
            <span className={cn("inline-flex items-center rounded-full border px-3 py-0.5 text-xs font-semibold", statusColor(service.status))}>
              {service.status}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
