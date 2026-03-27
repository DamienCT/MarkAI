# MARKAI n8n Workflow

One unified workflow handles all social media publishing.

## Setup

1. Open your n8n instance (`https://n8n.srv1191974.hstgr.cloud`)
2. **Workflows** > **Import from File** > select `markai-publish.json`
3. **Activate** (publish) the workflow
4. Set n8n environment variables (Settings > Variables):
   - `N8N_WEBHOOK_SECRET` = same value as in MARKAI `.env`
   - `MARKAI_API_URL` = `https://api.markai.srv1191974.hstgr.cloud`

## How It Works

```
MARKAI Backend
    │
    POST https://n8n.srv1191974.hstgr.cloud/webhook/markai/publish
    │  { content_id, channel, caption, hashtags, image_url, ...credentials }
    ▼
n8n Webhook → Set Variables → Route by Channel (Switch)
    ├── instagram → IG Create Container → IG Publish → Callback
    ├── facebook  → FB Publish → Callback
    ├── linkedin  → LinkedIn REST Posts API → Callback
    ├── youtube   → Not Implemented (skipped)
    ├── tiktok    → Not Implemented (skipped)
    └── x         → Not Implemented (skipped)
    │
    ▼
Callback to MARKAI Backend
    POST /api/v1/webhooks/publish-result
    { content_id, status: "published"|"failed", platform_post_id }
```

## MARKAI `.env` Configuration

```env
N8N_BASE_URL=https://n8n.srv1191974.hstgr.cloud
N8N_WEBHOOK_BASE=https://n8n.srv1191974.hstgr.cloud/webhook
N8N_WEBHOOK_SECRET=<same-secret-as-set-in-n8n>
```

The backend calls `{N8N_WEBHOOK_BASE}/markai/publish` with the channel and credentials in the payload.

## Supported Channels

| Channel | Status | API |
|---------|--------|-----|
| Instagram | Active | Meta Graph API v25.0 (2-step container publish) |
| Facebook | Active | Meta Graph API v25.0 |
| LinkedIn | Active | LinkedIn REST Posts API (version 202603) |
| YouTube | Placeholder | Returns "skipped" |
| TikTok | Placeholder | Returns "skipped" |
| X (Twitter) | Placeholder | Returns "skipped" |

## Credentials

Social platform credentials (access tokens, page IDs, etc.) are **not stored in n8n**. They're passed in the webhook payload by the MARKAI backend, which reads them from per-brand channel configuration in the database.

## Node Versions (n8n 2.13+, March 2026)

- Webhook: 2.1
- HTTP Request: 4.4
- Switch: 3.4
- Set: 3.4
- Respond to Webhook: 1.5
