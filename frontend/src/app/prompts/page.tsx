"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { PromptVersion } from "@/types";

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<PromptVersion[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchPrompts() {
      try {
        const data = await api.get<PromptVersion[]>("/api/v1/prompts", { limit: 50 });
        setPrompts(data);
      } catch {
        // Handle error
      } finally {
        setLoading(false);
      }
    }
    fetchPrompts();
  }, []);

  const handleWeightChange = async (id: string, weight: number) => {
    try {
      await api.patch(`/api/v1/prompts/${id}`, { a_b_weight: weight });
      setPrompts((prev) =>
        prev.map((p) => (p.id === id ? { ...p, a_b_weight: weight } : p))
      );
    } catch {
      // Handle error
    }
  };

  const handleToggleActive = async (id: string, isActive: boolean) => {
    try {
      await api.patch(`/api/v1/prompts/${id}`, { is_active: !isActive });
      setPrompts((prev) =>
        prev.map((p) => (p.id === id ? { ...p, is_active: !isActive } : p))
      );
    } catch {
      // Handle error
    }
  };

  const groupedPrompts = prompts.reduce(
    (acc, prompt) => {
      if (!acc[prompt.prompt_name]) acc[prompt.prompt_name] = [];
      acc[prompt.prompt_name].push(prompt);
      return acc;
    },
    {} as Record<string, PromptVersion[]>
  );

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Prompt Lab</h1>
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Prompt Lab</h1>
        <p className="text-muted-foreground">Manage prompt versions and A/B testing</p>
      </div>

      {Object.keys(groupedPrompts).length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">No prompt versions found</p>
          </CardContent>
        </Card>
      ) : (
        Object.entries(groupedPrompts).map(([name, versions]) => (
          <Card key={name}>
            <CardHeader>
              <CardTitle className="text-lg">{name}</CardTitle>
              <CardDescription>{versions.length} version(s)</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Version</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>A/B Weight</TableHead>
                    <TableHead>Performance</TableHead>
                    <TableHead>Usage</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {versions
                    .sort((a, b) => b.version - a.version)
                    .map((prompt) => (
                      <TableRow key={prompt.id}>
                        <TableCell className="font-medium">v{prompt.version}</TableCell>
                        <TableCell>{prompt.model_id}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Input
                              type="number"
                              min={0}
                              max={100}
                              value={Math.round(prompt.a_b_weight * 100)}
                              onChange={(e) =>
                                handleWeightChange(prompt.id, parseInt(e.target.value) / 100)
                              }
                              className="w-20 h-8"
                            />
                            <span className="text-xs text-muted-foreground">%</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          {prompt.performance_score !== undefined && prompt.performance_score !== null
                            ? `${(prompt.performance_score * 100).toFixed(1)}%`
                            : "N/A"}
                        </TableCell>
                        <TableCell>{prompt.usage_count}</TableCell>
                        <TableCell>
                          <Badge variant={prompt.is_active ? "default" : "outline"}>
                            {prompt.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {formatDate(prompt.created_at)}
                        </TableCell>
                        <TableCell>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleToggleActive(prompt.id, prompt.is_active)}
                          >
                            {prompt.is_active ? "Deactivate" : "Activate"}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
