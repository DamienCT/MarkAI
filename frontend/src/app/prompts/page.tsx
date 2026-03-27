"use client";

import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Info, Eye } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { PromptVersion } from "@/types";

interface AIModelOption {
  id: string;
  model_id: string;
  display_name: string | null;
  provider: string;
}

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<PromptVersion[]>([]);
  const [loading, setLoading] = useState(true);

  // View Template dialog
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [viewingPrompt, setViewingPrompt] = useState<PromptVersion | null>(null);

  // Create Version dialog
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [models, setModels] = useState<AIModelOption[]>([]);
  const [createForm, setCreateForm] = useState({
    prompt_name: "",
    template: "",
    model_id: "",
  });
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    async function fetchPrompts() {
      try {
        const data = await api.get<PromptVersion[]>("/api/v1/prompts", { limit: 50 });
        setPrompts(data);
      } catch {
        toast.error("Failed to load prompts");
      } finally {
        setLoading(false);
      }
    }
    fetchPrompts();
  }, []);

  const fetchModels = async () => {
    try {
      const data = await api.get<AIModelOption[]>("/api/v1/providers/models");
      setModels(data);
    } catch {
      // Models may fail to load; the select will be empty
    }
  };

  const handleWeightChange = async (id: string, weight: number) => {
    try {
      await api.patch(`/api/v1/prompts/${id}`, { a_b_weight: weight });
      setPrompts((prev) =>
        prev.map((p) => (p.id === id ? { ...p, a_b_weight: weight } : p))
      );
      toast.success("Weight updated");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update weight";
      toast.error(detail);
    }
  };

  const handleToggleActive = async (id: string, isActive: boolean) => {
    try {
      await api.patch(`/api/v1/prompts/${id}`, { is_active: !isActive });
      setPrompts((prev) =>
        prev.map((p) => (p.id === id ? { ...p, is_active: !isActive } : p))
      );
      toast.success(isActive ? "Prompt deactivated" : "Prompt activated");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to update prompt";
      toast.error(detail);
    }
  };

  const handleViewTemplate = (prompt: PromptVersion) => {
    setViewingPrompt(prompt);
    setViewDialogOpen(true);
  };

  const handleOpenCreateDialog = () => {
    fetchModels();
    setCreateForm({ prompt_name: "", template: "", model_id: "" });
    setCreateDialogOpen(true);
  };

  const handleCreateVersion = async () => {
    if (!createForm.prompt_name.trim()) {
      toast.error("Prompt name is required");
      return;
    }
    if (!createForm.template.trim()) {
      toast.error("Template is required");
      return;
    }
    if (!createForm.model_id) {
      toast.error("Please select a model");
      return;
    }

    setCreating(true);
    try {
      const newPrompt = await api.post<PromptVersion>("/api/v1/prompts", {
        prompt_name: createForm.prompt_name.trim(),
        template: createForm.template.trim(),
        model_id: createForm.model_id,
      });
      setPrompts((prev) => [newPrompt, ...prev]);
      toast.success("Prompt version created");
      setCreateDialogOpen(false);
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to create prompt version";
      toast.error(detail);
    } finally {
      setCreating(false);
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
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold">Prompt Lab</h1>
          <p className="text-muted-foreground">Manage prompt versions and A/B testing</p>
        </div>
        <Button onClick={handleOpenCreateDialog}>Create Version</Button>
      </div>

      {/* Info Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950">
        <Info className="h-5 w-5 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
        <p className="text-sm text-blue-800 dark:text-blue-200">
          Manage AI prompt templates used for content generation. Each prompt can have multiple versions with A/B testing weights.
          Adjust weights to control traffic distribution between versions and monitor performance scores to optimize your prompts.
        </p>
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
                              onChange={(e) => handleWeightChange(prompt.id, parseInt(e.target.value) / 100)}
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
                        <TableCell className="text-muted-foreground text-sm">{formatDate(prompt.created_at)}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleViewTemplate(prompt)}
                              title="View Template"
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleToggleActive(prompt.id, prompt.is_active)}
                            >
                              {prompt.is_active ? "Deactivate" : "Activate"}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        ))
      )}

      {/* View Template Dialog */}
      <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>
              {viewingPrompt?.prompt_name} - v{viewingPrompt?.version}
            </DialogTitle>
            <DialogDescription>
              Model: {viewingPrompt?.model_id} | Weight: {viewingPrompt ? Math.round(viewingPrompt.a_b_weight * 100) : 0}%
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <p className="text-sm font-medium mb-1">Template</p>
              <pre className="whitespace-pre-wrap rounded-md border bg-muted p-4 text-sm max-h-[400px] overflow-y-auto">
                {viewingPrompt?.template}
              </pre>
            </div>
            {viewingPrompt?.variables && viewingPrompt.variables.length > 0 && (
              <div>
                <p className="text-sm font-medium mb-1">Variables</p>
                <div className="flex flex-wrap gap-1">
                  {viewingPrompt.variables.map((v) => (
                    <Badge key={v} variant="outline">{v}</Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Create Version Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Create Prompt Version</DialogTitle>
            <DialogDescription>
              Add a new prompt template version for content generation.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">Prompt Name *</label>
              <Input
                placeholder="e.g. instagram_caption, blog_post"
                value={createForm.prompt_name}
                onChange={(e) => setCreateForm((f) => ({ ...f, prompt_name: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Template *</label>
              <textarea
                className="flex min-h-[150px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 font-mono"
                placeholder="Write your prompt template here. Use {{variable}} for template variables."
                value={createForm.template}
                onChange={(e) => setCreateForm((f) => ({ ...f, template: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Model *</label>
              <Select
                value={createForm.model_id}
                onValueChange={(v) => setCreateForm((f) => ({ ...f, model_id: v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a model" />
                </SelectTrigger>
                <SelectContent>
                  {models.map((m) => (
                    <SelectItem key={m.id} value={m.model_id}>
                      {m.display_name || m.model_id} ({m.provider})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleCreateVersion} disabled={creating}>
              {creating ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
