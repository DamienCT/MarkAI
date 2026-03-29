export type Channel =
  | "instagram"
  | "facebook"
  | "linkedin"
  | "youtube"
  | "tiktok"
  | "x"
  | "website_blog"
  | "teams";

export const ALL_CHANNELS: Channel[] = [
  "instagram", "facebook", "linkedin", "youtube",
  "tiktok", "x", "website_blog", "teams",
];

export const CHANNEL_DISPLAY_NAMES: Record<Channel, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  youtube: "YouTube",
  tiktok: "TikTok",
  x: "X (Twitter)",
  website_blog: "Website / Blog",
  teams: "Teams",
};

export interface ChannelConfig {
  enabled: boolean;
  configured: boolean;
  handle?: string;
  access_token?: string;
  page_id?: string;
  org_id?: string;
  channel_id?: string;
  api_key?: string;
  url?: string;
  webhook_url?: string;
}

export interface Brand {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  logo_url: string | null;
  brand_guidelines: Record<string, unknown>;
  tone_of_voice: string | null;
  target_audience: Record<string, unknown>;
  color_palette: Record<string, unknown>;
  is_active: boolean;
  is_bc_linked: boolean;
  bc_company: string | null;
  bc_locations: string[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
  status: 'onboarding' | 'activating' | 'active' | 'inactive';
  onboarding_completed_at: string | null;
  activation_started_at: string | null;
  // Optional relationship fields (may not be populated on all responses)
  competitors?: Competitor[];
  industry?: string;
  website_url?: string;
  voice_profile?: VoiceProfile;
  social_accounts?: SocialAccount[];
}

export interface VoiceProfile {
  tone: string[];
  style: string;
  vocabulary_level: string;
  emoji_usage: string;
  hashtag_strategy: string;
  dos: string[];
  donts: string[];
}

export interface SocialAccount {
  platform: string;
  handle: string;
  account_id?: string;
  access_token?: string;
  refresh_token?: string;
  connected: boolean;
  followers_count?: number;
}

export interface Competitor {
  id?: string;
  name: string;
  website_url?: string;
  social_handles: Record<string, string>;
  notes?: string;
}

export interface Content {
  id: string;
  brand_id: string;
  brand_name?: string;
  campaign_id?: string;
  title: string;
  caption: string;
  hashtags: string[];
  cta?: string;
  status: ContentStatus;
  content_type: string;
  platform: string;
  platform_adaptations?: Record<string, PlatformAdaptation>;
  media_urls: string[];
  thumbnail_url?: string;
  scheduled_at?: string;
  published_at?: string;
  engagement_metrics?: EngagementMetrics;
  ai_model_used?: string;
  prompt_version_id?: string;
  generation_metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type ContentStatus =
  | "queued"
  | "working"
  | "in_review"
  | "reworking"
  | "approved"
  | "scheduled"
  | "published"
  | "failed";

export interface PlatformAdaptation {
  caption: string;
  hashtags: string[];
  media_specs?: Record<string, unknown>;
}

export interface CalendarItem {
  id: string;
  brand_id: string;
  campaign_id?: string | null;
  title: string;
  description?: string | null;
  item_type?: string;
  channel: Channel;
  scheduled_at: string | null;
  published_at?: string | null;
  status: string;
  assigned_to?: string | null;
  product_ids?: string[];
  tags?: string[];
  priority?: number;
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface Campaign {
  id: string;
  brand_id: string;
  name: string;
  description: string;
  status: "draft" | "active" | "paused" | "completed" | "archived";
  start_date: string;
  end_date: string;
  content_count: number;
  created_at: string;
  updated_at: string;
}

export interface Approval {
  id: string;
  content_id: string;
  content?: Content;
  reviewer_id?: string;
  reviewer_name?: string;
  status: "pending" | "approved" | "rejected" | "revision_requested";
  comments?: string;
  decided_at?: string;
  created_at: string;
}

export interface Product {
  id: string;
  brand_id: string;
  name: string;
  bc_item_no: string | null;
  bc_item_category: string | null;
  description: string | null;
  short_description: string | null;
  sku: string | null;
  barcode: string | null;
  unit_price: number | null;
  currency: string | null;
  category: string | null;
  subcategory: string | null;
  attributes: Record<string, unknown> | null;
  tags: string[] | null;
  image_urls: Record<string, unknown> | null;
  primary_image_url: string | null;
  vendor_name: string | null;
  vendor_no: string | null;
  bc_company: string | null;
  bc_location: string | null;
  remaining_qty: number | null;
  lot_no: string | null;
  is_active: boolean;
  is_new: boolean;
  is_expiring_soon: boolean;
  expiry_date: string | null;
  bc_last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url?: string;
  role: "admin" | "manager" | "editor" | "viewer";
  brand_ids: string[];
  is_active: boolean;
  last_login?: string;
  created_at: string;
}

export interface EngagementMetrics {
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  impressions: number;
  reach: number;
  engagement_rate: number;
  clicks?: number;
  video_views?: number;
}

export interface AgentRun {
  id: string;
  agent_type: string;
  brand_id?: string;
  trigger?: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  input_payload?: Record<string, unknown>;
  output_payload?: Record<string, unknown>;
  error_message?: string;
  tokens_used?: number;
  cost_usd?: number;
  duration_ms?: number;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface PromptVersion {
  id: string;
  prompt_name: string;
  version: number;
  template: string;
  variables: string[];
  model_id: string;
  a_b_weight: number;
  is_active: boolean;
  performance_score?: number;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

export interface Adaptation {
  id: string;
  source_content_id: string;
  target_channel: string;
  adapted_text?: string | null;
  adapted_headline?: string | null;
  adapted_hashtags?: string[] | null;
  adapted_media?: Record<string, unknown> | null;
  adaptation_notes?: string | null;
  ai_model?: string | null;
  status: string;
  tier?: string;
  category?: string;
  description?: string;
  confidence_score: number;
  evidence?: string[];
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Notification {
  id: string;
  user_id: string;
  type: string;
  title: string;
  message: string;
  read: boolean;
  action_url?: string;
  created_at: string;
}

export interface ServiceStatus {
  name: string;
  status: "healthy" | "degraded" | "down";
  latency_ms?: number;
  last_check: string;
  details?: Record<string, unknown>;
}

export interface SchedulerJob {
  id: string;
  name: string;
  schedule: string;
  last_run?: string;
  next_run?: string;
  status: "active" | "paused" | "failed";
  run_count: number;
}

export interface QueueInfo {
  name: string;
  pending: number;
  processing: number;
  failed: number;
  completed: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface DashboardStats {
  active_brands: number;
  pending_approvals: number;
  content_in_pipeline: number;
  published_this_week: number;
  scheduled_posts: number;
  recent_agent_runs: AgentRun[];
  upcoming_posts: CalendarItem[];
}

export interface AIProvider {
  id: string;
  name: string;
  provider_type: string;
  model_id: string;
  is_active: boolean;
  config: Record<string, unknown>;
  usage_today: number;
  daily_limit: number;
  cost_today: number;
}

export interface AIModelCategory {
  id: string;
  slug: string;
  display_name: string;
  description: string | null;
  active_model?: AIModel | null;
}

export interface AIModel {
  id: string;
  provider: string;
  model_id: string;
  display_name: string | null;
  category_id: string | null;
  is_available: boolean;
  capabilities: Record<string, unknown>;
  discovered_at: string;
}

export interface AIModelSelection {
  category_slug: string;
  model_id: string;
  is_active: boolean;
  priority: number;
}

export interface AuditLogEntry {
  id: string;
  user_id?: string;
  user_name?: string;
  action: string;
  resource_type: string;
  resource_id?: string;
  details?: Record<string, unknown>;
  ip_address?: string;
  created_at: string;
}
