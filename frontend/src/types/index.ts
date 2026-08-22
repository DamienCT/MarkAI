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

export interface ChannelConfigField {
  key: string;
  label: string;
  placeholder: string;
  optional?: boolean;
}

// Canonical per-channel config form fields — single source of truth.
// Keys match the backend credential contract exactly
// (brand_guidelines.channels.<channel>.<field>) — the publishers read these
// keys verbatim, so never rename one here without the backend moving too.
// See docs/CHANNEL_CREDENTIALS.md for where each value comes from.
export const CHANNEL_CONFIG_FIELDS: Record<Channel, ChannelConfigField[]> = {
  instagram: [
    { key: "handle", label: "Handle", placeholder: "@yourbrand" },
    { key: "account_id", label: "Business Account ID", placeholder: "ex: 17841405822304914" },
    { key: "access_token", label: "Access Token", placeholder: "Meta access token" },
  ],
  facebook: [
    { key: "page_id", label: "Page ID", placeholder: "Facebook Page ID" },
    { key: "access_token", label: "Access Token", placeholder: "Meta access token" },
  ],
  linkedin: [
    { key: "org_id", label: "Organization ID", placeholder: "LinkedIn Org ID" },
    { key: "access_token", label: "Access Token", placeholder: "LinkedIn access token" },
    { key: "client_id", label: "Client ID", placeholder: "LinkedIn app Client ID" },
    { key: "client_secret", label: "Client Secret", placeholder: "LinkedIn app Client Secret" },
  ],
  youtube: [
    { key: "channel_id", label: "Channel ID", placeholder: "YouTube Channel ID" },
    { key: "api_key", label: "API Key", placeholder: "YouTube API key" },
  ],
  tiktok: [
    { key: "handle", label: "Handle (optional)", placeholder: "@yourbrand", optional: true },
    { key: "client_key", label: "Client Key", placeholder: "TikTok app client key" },
    { key: "client_secret", label: "Client Secret", placeholder: "TikTok app client secret" },
    { key: "access_token", label: "Access Token", placeholder: "TikTok access token (24h lifetime)" },
    { key: "refresh_token", label: "Refresh Token (optional)", placeholder: "Enables automatic token refresh", optional: true },
  ],
  x: [
    { key: "handle", label: "Handle (optional)", placeholder: "@yourbrand", optional: true },
    { key: "consumer_key", label: "Consumer Key (API Key)", placeholder: "X app consumer key" },
    { key: "consumer_secret", label: "Consumer Secret", placeholder: "X app consumer secret" },
    { key: "access_token", label: "Access Token", placeholder: "X user access token" },
    { key: "access_token_secret", label: "Access Token Secret", placeholder: "X user access token secret" },
  ],
  website_blog: [
    { key: "platform", label: "Platform (optional)", placeholder: "wordpress (default)", optional: true },
    { key: "base_url", label: "Site URL", placeholder: "https://blog.example.com" },
    { key: "username", label: "Username", placeholder: "WordPress username" },
    { key: "app_password", label: "Application Password", placeholder: "WordPress application password" },
  ],
  teams: [
    { key: "webhook_url", label: "Teams Webhook URL", placeholder: "https://outlook.office.com/webhook/..." },
  ],
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
  color_palette: { primary?: string; secondary?: string; accent?: string } | Record<string, unknown>;
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
  calendar_item_id?: string;
  brand_name?: string;
  campaign_id?: string;
  // Backend uses "headline", frontend historically used "title"
  title?: string;
  headline?: string;
  caption?: string;
  body_text?: string;
  hashtags?: string[];
  cta?: string;
  cta_text?: string;
  status?: ContentStatus;
  content_type?: string;
  platform?: string;
  platform_adaptations?: Record<string, PlatformAdaptation>;
  platform_metadata?: Record<string, unknown>;
  media_urls?: string[];
  image_urls?: Record<string, unknown> | string[];
  thumbnail_url?: string;
  /** MinIO object path of the rendered reel video (e.g. videos/{brand}/{item}/final.mp4) */
  video_url?: string;
  scheduled_at?: string;
  published_at?: string;
  engagement_metrics?: EngagementMetrics;
  ai_model_used?: string;
  ai_model?: string;
  prompt_version_id?: string;
  ai_prompt_version?: string;
  generation_metadata?: Record<string, unknown>;
  ai_generated?: boolean;
  is_current?: boolean;
  version?: number;
  created_at: string;
  updated_at: string;
}

export type ContentStatus =
  | "queued"
  | "working"
  | "in_review"
  | "reworking"
  | "rendering"
  | "approved"
  | "scheduled"
  | "publishing"
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
  brand_name?: string;
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
  pillar?: string;
  theme?: string;
  target_audience?: string;
  content_brief?: string;
  generation_metadata?: {
    current_step?: string;
    step_index?: number;
    total_steps?: number;
    [key: string]: unknown;
  };
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
  feedback?: string; // reviewer remark (API field; `comments` kept for back-compat)
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
  status: "pending" | "running" | "paused_for_review" | "completed" | "failed" | "cancelled";
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

export interface ActiveAgentRun {
  id: string;
  agent_type: string;
  trigger?: string;
  brand_id?: string;
  status: string;
  started_at?: string;
  input_payload?: Record<string, unknown>;
  output_payload?: Record<string, unknown>;
  calendar_item_id?: string;
  current_step?: string;
  step_index?: number;
  total_steps?: number;
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

// Matches the backend serializer in app/api/v1/learning.py. The adaptations
// table has no tier/confidence columns — the evaluation workflow packs them
// into the adaptation_notes JSON envelope and the API lifts them to
// top-level keys (numeric tier 1..3 and confidence 0..1, defaulting to
// 2 / 0.5 for malformed or legacy free-text notes).
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
  /** Lifted from the notes envelope: 1 (post) | 2 (campaign) | 3 (strategy). */
  tier?: number;
  /** Lifted from the notes envelope: 0..1. */
  confidence?: number;
  /** Lifted from the notes envelope: workflow-specific detail payload. */
  data?: Record<string, unknown> | null;
  created_at: string;
}

// Matches the backend serializer in app/api/v1/notifications.py.
export interface Notification {
  id: string;
  notification_type: string;
  title: string;
  body: string | null;
  channel?: string | null;
  reference_type: string | null;
  reference_id: string | null;
  is_read: boolean;
  read_at?: string | null;
  sent_at?: string | null;
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
  // Backend (APScheduler) shape: cron/interval expression + next fire time.
  trigger: string;
  next_run_time?: string | null;
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
  active_workflows?: number;
  workflows_running_pending?: number;
  workflows_completed?: number;
  workflows_failed?: number;
  monthly_goal?: { published: number; target: number };
  recent_agent_runs?: AgentRun[];
  upcoming_posts?: CalendarItem[];
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

export type EventSource = "manual" | "ai_detected";

export interface Event {
  id: string;
  brand_id: string | null;
  title: string;
  description: string | null;
  start_date: string;
  end_date: string | null;
  is_annual: boolean;
  category: string | null;
  source: EventSource;
  created_at: string;
  updated_at: string;
}

export interface EventCreate {
  brand_id?: string | null;
  title: string;
  description?: string | null;
  start_date: string;
  end_date?: string | null;
  is_annual?: boolean;
  category?: string | null;
}

export interface EventUpdate {
  brand_id?: string | null;
  title?: string;
  description?: string | null;
  start_date?: string;
  end_date?: string | null;
  is_annual?: boolean;
  category?: string | null;
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
