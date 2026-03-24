# MARKAI n8n Workflows

Automation workflows that receive publish requests from the MARKAI backend and post content to social media platforms, then report the result back via webhook callback.

## Architecture

```
MARKAI Backend                    n8n                         Social Platform
     |                             |                               |
     |-- POST /markai/publish/X -->|                               |
     |<-- 202 Accepted ------------|                               |
     |                             |-- Platform API POST --------->|
     |                             |<-- platform_post_id ----------|
     |<-- POST /publish-result ----|                               |
     |   (status, post_id)         |                               |
```

## Importing Workflows

1. Open your n8n instance (default: `http://localhost:5678`)
2. Go to **Settings** (gear icon) > **Import from File**
3. Select the JSON file for the workflow you want to import
4. Alternatively, use the n8n CLI:
   ```bash
   n8n import:workflow --input=instagram-publish.json
   n8n import:workflow --input=facebook-publish.json
   n8n import:workflow --input=linkedin-publish.json
   n8n import:workflow --input=youtube-publish.json
   n8n import:workflow --input=tiktok-publish.json
   n8n import:workflow --input=x-publish.json
   n8n import:workflow --input=engagement-pull.json
   ```
5. After importing, **activate** each workflow (toggle switch in the top right)

## Environment Variables Required in n8n

Set these in your n8n environment (docker-compose or `.env`):

| Variable | Description |
|----------|-------------|
| `MARKAI_API_URL` | Base URL of the MARKAI backend (e.g. `http://backend:8000`) |
| `N8N_WEBHOOK_SECRET` | Shared secret for authenticating callbacks to MARKAI |

## Webhook URLs (MARKAI -> n8n)

These are the endpoints the MARKAI `publish_service.py` dispatches to. They must match the value of `N8N_WEBHOOK_BASE` in the MARKAI `.env` file.

| Workflow | Webhook Path |
|----------|-------------|
| Instagram | `POST {N8N_WEBHOOK_BASE}/markai/publish/instagram` |
| Facebook | `POST {N8N_WEBHOOK_BASE}/markai/publish/facebook` |
| LinkedIn | `POST {N8N_WEBHOOK_BASE}/markai/publish/linkedin` |
| YouTube | `POST {N8N_WEBHOOK_BASE}/markai/publish/youtube` |
| TikTok | `POST {N8N_WEBHOOK_BASE}/markai/publish/tiktok` |
| X (Twitter) | `POST {N8N_WEBHOOK_BASE}/markai/publish/x` |
| Engagement | `POST {N8N_WEBHOOK_BASE}/markai/engagement/pull` (manual) + scheduled every 6h |

## Callback Structure (n8n -> MARKAI)

All publish workflows call back to the MARKAI backend after attempting to post:

**Endpoint:** `POST {MARKAI_API_URL}/api/v1/webhooks/publish-result`

**Headers:**
```
X-Webhook-Secret: {N8N_WEBHOOK_SECRET}
Content-Type: application/json
```

**Success payload:**
```json
{
  "content_id": "uuid",
  "status": "published",
  "platform_post_id": "platform-specific-id",
  "published_at": "2026-03-24T12:00:00.000Z"
}
```

**Failure payload:**
```json
{
  "content_id": "uuid",
  "status": "failed",
  "error_message": "Description of what went wrong"
}
```

## Per-Platform Credentials

Credentials are passed in the webhook payload from MARKAI (sourced from brand guidelines config). Each platform requires:

### Instagram
- `meta_access_token` - Meta Graph API long-lived page access token
- `instagram_account_id` - Instagram Business Account ID
- Required scopes: `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`

### Facebook
- `meta_access_token` - Meta Graph API page access token
- `page_id` - Facebook Page ID
- Required scopes: `pages_manage_posts`, `pages_read_engagement`

### LinkedIn
- `linkedin_access_token` - LinkedIn OAuth 2.0 access token
- `linkedin_org_id` - LinkedIn Organization ID (numeric)
- Required scopes: `w_organization_social`, `r_organization_social`

### YouTube
- `api_key` - OAuth 2.0 access token (from YouTube Data API)
- `channel_id` - YouTube Channel ID
- Required scopes: `https://www.googleapis.com/auth/youtube.upload`

### TikTok
- `access_token` - TikTok OAuth access token
- Required scopes: `video.publish`, `video.upload`

### X (Twitter)
- `api_key` - OAuth 2.0 Bearer token (or API key for OAuth 1.0a)
- Required scopes: `tweet.write`, `tweet.read`, `users.read`

## Workflow Details

### instagram-publish.json
1. Receives webhook with image URL and caption
2. Creates a media container via `POST /{ig_account_id}/media`
3. Publishes the container via `POST /{ig_account_id}/media_publish`
4. Callbacks with the published media ID
5. On any error, callbacks with `status: failed` and the error message

### facebook-publish.json
1. Receives webhook with message, optional image URL, optional link
2. Branches: if image present, posts to `/{page_id}/photos`; otherwise posts to `/{page_id}/feed`
3. Callbacks with the post ID

### linkedin-publish.json
1. Receives webhook with text, optional image URL
2. If image: registers upload -> downloads image -> creates UGC post with image media
3. If no image: creates text-only UGC post
4. Callbacks with the post URN

### youtube-publish.json
1. Receives webhook with video URL, title, description, tags
2. Downloads video binary from MinIO/storage URL
3. Initiates a resumable upload to YouTube Data API v3
4. Uploads the video binary
5. Callbacks with the YouTube video ID

### tiktok-publish.json
1. Receives webhook with video URL and caption
2. Initializes a post via TikTok Content Posting API v2 (PULL_FROM_URL source)
3. Checks publish status
4. Callbacks with the publish/share ID

### x-publish.json
1. Receives webhook with text and optional image
2. Truncates text + hashtags to 280 characters
3. If image: downloads, uploads to Twitter media endpoint, attaches to tweet
4. Posts tweet via X API v2
5. Callbacks with tweet ID

### engagement-pull.json
1. Runs every 6 hours (or triggered manually via webhook)
2. Fetches published posts from MARKAI API
3. Routes each post to its platform's analytics/insights API
4. Posts engagement metrics back to MARKAI

## Testing

### Test with curl

```bash
# Test Instagram publish (replace values)
curl -X POST http://localhost:5678/webhook/markai/publish/instagram \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "test-uuid-123",
    "channel": "instagram",
    "caption": "Test post from MARKAI",
    "hashtags": ["markai", "test"],
    "image_url": "https://example.com/test-image.jpg",
    "meta_access_token": "YOUR_TOKEN",
    "instagram_account_id": "YOUR_IG_ID"
  }'

# Test Facebook publish
curl -X POST http://localhost:5678/webhook/markai/publish/facebook \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "test-uuid-456",
    "channel": "facebook",
    "caption": "Test post from MARKAI",
    "hashtags": ["markai"],
    "image_url": "",
    "cta_url": "https://example.com",
    "meta_access_token": "YOUR_TOKEN",
    "page_id": "YOUR_PAGE_ID"
  }'

# Test X publish
curl -X POST http://localhost:5678/webhook/markai/publish/x \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "test-uuid-789",
    "channel": "x",
    "caption": "Test tweet from MARKAI",
    "hashtags": ["markai"],
    "image_url": "",
    "api_key": "YOUR_BEARER_TOKEN"
  }'

# Manually trigger engagement pull
curl -X POST http://localhost:5678/webhook/markai/engagement/pull
```

### Test the callback endpoint

```bash
# Simulate a successful publish callback
curl -X POST http://localhost:8000/api/v1/webhooks/publish-result \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your-secret-here" \
  -d '{
    "content_id": "your-content-uuid",
    "status": "published",
    "platform_post_id": "12345_67890",
    "published_at": "2026-03-24T12:00:00Z"
  }'
```

## Error Handling

Each workflow uses n8n's `onError: continueErrorOutput` pattern on HTTP Request nodes. When a platform API call fails:

1. The error output branch is activated
2. A callback is sent to MARKAI with `status: "failed"` and the error message
3. The webhook still responds with 202 to avoid the MARKAI backend timing out
4. The MARKAI backend updates the calendar item status to `"failed"` and stores the error in `generation_metadata.publish_error`

## Troubleshooting

- **Workflow not receiving requests**: Ensure the workflow is activated and the webhook URL in n8n matches `N8N_WEBHOOK_BASE` in MARKAI's `.env`
- **401/403 from platform APIs**: Check that access tokens are valid and have the required scopes
- **Callback not reaching MARKAI**: Verify `MARKAI_API_URL` is set in n8n's environment and the backend is reachable from the n8n container
- **Image upload fails**: Ensure `image_url` is publicly accessible (or accessible from the n8n container if using internal MinIO URLs)
