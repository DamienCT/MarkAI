"use client";

import React, { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ContentEditor } from "@/components/content/ContentEditor";
import { PlatformMockups } from "@/components/content/PlatformMockups";
import { ApprovalHistory } from "@/components/approval/ApprovalHistory";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, API_BASE_URL } from "@/lib/api";
import type { Content, Approval } from "@/types";

export default function ContentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const contentId = params.id as string;

  const [content, setContent] = useState<Content | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const [contentData, approvalData] = await Promise.allSettled([
          api.get<Content>(`/api/v1/content/${contentId}`),
          api.get<Approval[]>(`/api/v1/approvals`, { content_id: contentId }),
        ]);
        if (contentData.status === "fulfilled") setContent(contentData.value);
        if (approvalData.status === "fulfilled") setApprovals(approvalData.value);
      } catch {
        toast.error("Failed to load content");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [contentId]);

  const handleSave = async (data: Partial<Content>) => {
    try {
      const updated = await api.put<Content>(`/api/v1/content/${contentId}`, data);
      setContent(updated);
      toast.success("Content saved");
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail || "Failed to save content";
      toast.error(detail);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-[600px] w-full" />
      </div>
    );
  }

  if (!content) {
    return (
      <div className="text-center py-12">
        <p className="text-lg text-muted-foreground">Content not found</p>
        <Button variant="outline" className="mt-4" onClick={() => router.push("/content")}>
          Back to Content Studio
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => router.push("/content")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-3xl font-bold">{content.title}</h1>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ContentEditor content={content} onSave={handleSave} />
        </div>
        <div className="space-y-6">
          {content.generation_metadata?.mockup_urls != null && (
            <PlatformMockups
              mockupUrls={content.generation_metadata.mockup_urls as Record<string, string>}
              imageBaseUrl={API_BASE_URL}
            />
          )}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Approval History</CardTitle>
            </CardHeader>
            <CardContent>
              <ApprovalHistory approvals={approvals} />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
