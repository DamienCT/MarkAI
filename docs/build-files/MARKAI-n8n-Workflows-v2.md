# MARKAI — n8n Workflow Setup Guide (v2)

## n8n's Role in MARKAI

n8n handles **one thing only: social platform API publishing.**

Everything else — scheduling, engagement pulling, error handling, BC sync triggers — lives in FastAPI as background tasks. This keeps n8n focused on what it's genuinely good at: making fiddly external API calls where visual debugging and easy credential tweaking matter.

**Total workflows: 3**

| # | Workflow | What it does |
|---|---------|-------------|
| 1 | Publish Instagram | Receives webhook from FastAPI, posts to Instagram Graph API, reports result |
| 2 | Publish Facebook | Same pattern for Facebook Pages API |
| 3 | Publish LinkedIn | Same pattern for LinkedIn UGC API |

---

## How It Works

```
FastAPI (publish_checker) → POST to n8n webhook → n8n calls social API → n8n POSTs result back to FastAPI
```

1. FastAPI's APScheduler checks every 15 minutes for content due to publish
2. For each due item, FastAPI builds the payload (caption, image URL, platform tokens) and POSTs to the matching n8n webhook
3. n8n makes the social platform API call
4. n8n calls `POST /api/v1/webhooks/publish-result` on FastAPI with the result
5. FastAPI updates content status to `published` or `failed`

**All tokens and credentials are passed in the webhook payload.** n8n does not store any social platform credentials — FastAPI owns them (from `.env` defaults or per-brand settings in PostgreSQL).

---

## Setup

1. Access n8n at `https://n8n.yourdomain.com`
2. Create admin account
3. Set these environment variables in n8n's Docker container:

```bash
N8N_ENCRYPTION_KEY=your-encryption-key
N8N_HOST=n8n.yourdomain.com
N8N_PROTOCOL=https
WEBHOOK_URL=https://n8n.yourdomain.com
MARKAI_API_URL=http://backend:8000
```

4. **Create one credential** in n8n → Settings → Credentials:

| Name | Type | Config |
|------|------|--------|
| `MARKAI API` | Header Auth | Name: `Authorization`, Value: `Bearer {your-internal-api-key}` |

5. Import each workflow JSON below
6. Activate all three workflows

---

## Webhook Payload Contract

**Inbound to n8n (from FastAPI):**
```json
{
    "content_id": "uuid-string",
    "caption": "Post caption with #hashtags",
    "image_url": "https://minio.example.com/markai-assets/content/123/final.jpg",
    "access_token": "platform-specific-token",
    "page_id": "facebook-page-id",
    "instagram_account_id": "ig-business-account-id",
    "org_id": "linkedin-org-id"
}
```

**Outbound from n8n (back to FastAPI):**
```json
{
    "content_id": "uuid-string",
    "platform": "instagram|facebook|linkedin",
    "status": "published|failed",
    "platform_post_id": "id-from-platform",
    "published_at": "2026-03-23T12:00:00Z",
    "error": "error message if failed"
}
```

---

## Workflow 1: Publish to Instagram

Handles single image posts. The coding agent will extend this for carousels (multiple media containers before the final publish call) and reels.

```json
{
  "name": "MARKAI - Publish Instagram",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "markai/publish/instagram",
        "authentication": "headerAuth",
        "responseMode": "responseNode",
        "options": {}
      },
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [240, 300],
      "id": "webhook-ig",
      "name": "Receive Publish Request",
      "webhookId": "markai-publish-instagram"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "=https://graph.facebook.com/v21.0/{{ $json.instagram_account_id }}/media",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ image_url: $json.image_url, caption: $json.caption, access_token: $json.access_token }) }}",
        "options": {
          "timeout": 60000,
          "redirect": { "redirect": { "followRedirects": true } }
        }
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [480, 300],
      "id": "create-container",
      "name": "Create Media Container"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "=https://graph.facebook.com/v21.0/{{ $('Receive Publish Request').item.json.instagram_account_id }}/media_publish",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ creation_id: $json.id, access_token: $('Receive Publish Request').item.json.access_token }) }}",
        "options": { "timeout": 60000 }
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [720, 300],
      "id": "publish-media",
      "name": "Publish Media"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{ $env.MARKAI_API_URL }}/api/v1/webhooks/publish-result",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ content_id: $('Receive Publish Request').item.json.content_id, platform: 'instagram', status: 'published', platform_post_id: $json.id, published_at: new Date().toISOString() }) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [960, 240],
      "id": "callback-success",
      "name": "Report Success",
      "credentials": {
        "httpHeaderAuth": {
          "id": "MARKAI API",
          "name": "MARKAI API"
        }
      }
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{ $env.MARKAI_API_URL }}/api/v1/webhooks/publish-result",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ content_id: $('Receive Publish Request').item.json.content_id, platform: 'instagram', status: 'failed', error: $json.error?.message || JSON.stringify($json), failed_at: new Date().toISOString() }) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [960, 420],
      "id": "callback-failure",
      "name": "Report Failure",
      "credentials": {
        "httpHeaderAuth": {
          "id": "MARKAI API",
          "name": "MARKAI API"
        }
      }
    },
    {
      "parameters": {
        "respondWith": "json",
        "responseBody": "={{ JSON.stringify({ status: 'accepted' }) }}",
        "options": { "responseCode": 200 }
      },
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.1,
      "position": [1200, 300],
      "id": "respond",
      "name": "Respond OK"
    }
  ],
  "connections": {
    "Receive Publish Request": {
      "main": [[{ "node": "Create Media Container", "type": "main", "index": 0 }]]
    },
    "Create Media Container": {
      "main": [[{ "node": "Publish Media", "type": "main", "index": 0 }]]
    },
    "Publish Media": {
      "main": [[{ "node": "Report Success", "type": "main", "index": 0 }]]
    },
    "Report Success": {
      "main": [[{ "node": "Respond OK", "type": "main", "index": 0 }]]
    }
  },
  "settings": {
    "executionOrder": "v1"
  },
  "pinData": {},
  "staticData": null
}
```

**Error handling note:** If the "Create Media Container" or "Publish Media" node fails (HTTP 4xx/5xx), n8n's default behavior stops execution. The coding agent should add an error output branch from each HTTP node that routes to "Report Failure" → "Respond OK". Use **Settings → Continue On Fail = true** on both HTTP nodes and add an IF node checking `$json.error` to route to success or failure paths.

---

## Workflow 2: Publish to Facebook

```json
{
  "name": "MARKAI - Publish Facebook",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "markai/publish/facebook",
        "authentication": "headerAuth",
        "responseMode": "responseNode",
        "options": {}
      },
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [240, 300],
      "id": "webhook-fb",
      "name": "Receive Publish Request",
      "webhookId": "markai-publish-facebook"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "=https://graph.facebook.com/v21.0/{{ $json.page_id }}/photos",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ url: $json.image_url, message: $json.caption, access_token: $json.access_token }) }}",
        "options": { "timeout": 60000 }
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [480, 300],
      "id": "post-photo",
      "name": "Post Photo to Page"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{ $env.MARKAI_API_URL }}/api/v1/webhooks/publish-result",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ content_id: $('Receive Publish Request').item.json.content_id, platform: 'facebook', status: 'published', platform_post_id: $json.post_id || $json.id, published_at: new Date().toISOString() }) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [720, 300],
      "id": "callback-fb",
      "name": "Report Result",
      "credentials": {
        "httpHeaderAuth": {
          "id": "MARKAI API",
          "name": "MARKAI API"
        }
      }
    },
    {
      "parameters": {
        "respondWith": "json",
        "responseBody": "={{ JSON.stringify({ status: 'accepted' }) }}",
        "options": { "responseCode": 200 }
      },
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.1,
      "position": [960, 300],
      "id": "respond-fb",
      "name": "Respond OK"
    }
  ],
  "connections": {
    "Receive Publish Request": {
      "main": [[{ "node": "Post Photo to Page", "type": "main", "index": 0 }]]
    },
    "Post Photo to Page": {
      "main": [[{ "node": "Report Result", "type": "main", "index": 0 }]]
    },
    "Report Result": {
      "main": [[{ "node": "Respond OK", "type": "main", "index": 0 }]]
    }
  },
  "settings": { "executionOrder": "v1" }
}
```

**For text-only posts** (no image), FastAPI will send the payload without `image_url`. The coding agent should add an IF node that checks whether `image_url` exists and routes to either `/photos` (image post) or `/feed` (text post) accordingly.

---

## Workflow 3: Publish to LinkedIn

```json
{
  "name": "MARKAI - Publish LinkedIn",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "markai/publish/linkedin",
        "authentication": "headerAuth",
        "responseMode": "responseNode",
        "options": {}
      },
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [240, 300],
      "id": "webhook-li",
      "name": "Receive Publish Request",
      "webhookId": "markai-publish-linkedin"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "https://api.linkedin.com/v2/ugcPosts",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            { "name": "X-Restli-Protocol-Version", "value": "2.0.0" },
            { "name": "Authorization", "value": "=Bearer {{ $json.access_token }}" },
            { "name": "Content-Type", "value": "application/json" }
          ]
        },
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ author: 'urn:li:organization:' + $json.org_id, lifecycleState: 'PUBLISHED', specificContent: { 'com.linkedin.ugc.ShareContent': { shareCommentary: { text: $json.caption }, shareMediaCategory: 'NONE' } }, visibility: { 'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC' } }) }}",
        "options": { "timeout": 60000 }
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [480, 300],
      "id": "post-li",
      "name": "Post to LinkedIn"
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{ $env.MARKAI_API_URL }}/api/v1/webhooks/publish-result",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ content_id: $('Receive Publish Request').item.json.content_id, platform: 'linkedin', status: 'published', platform_post_id: $json.id, published_at: new Date().toISOString() }) }}",
        "options": {}
      },
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [720, 300],
      "id": "callback-li",
      "name": "Report Result",
      "credentials": {
        "httpHeaderAuth": {
          "id": "MARKAI API",
          "name": "MARKAI API"
        }
      }
    },
    {
      "parameters": {
        "respondWith": "json",
        "responseBody": "={{ JSON.stringify({ status: 'accepted' }) }}",
        "options": { "responseCode": 200 }
      },
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.1,
      "position": [960, 300],
      "id": "respond-li",
      "name": "Respond OK"
    }
  ],
  "connections": {
    "Receive Publish Request": {
      "main": [[{ "node": "Post to LinkedIn", "type": "main", "index": 0 }]]
    },
    "Post to LinkedIn": {
      "main": [[{ "node": "Report Result", "type": "main", "index": 0 }]]
    },
    "Report Result": {
      "main": [[{ "node": "Respond OK", "type": "main", "index": 0 }]]
    }
  },
  "settings": { "executionOrder": "v1" }
}
```

**For image posts on LinkedIn**, the flow requires a 3-step process: (1) register image upload, (2) upload binary to the returned URL, (3) create post referencing the uploaded asset. The coding agent should extend this template with those steps, using an IF node to branch between text-only and image posts.

---

## How to Import

1. In n8n, click **Workflows → Add Workflow → three dots menu → Import from File**
2. Paste or upload each JSON
3. After import, click on nodes that reference `MARKAI API` credential and re-select it from the dropdown
4. **Activate** each workflow (toggle in top-right corner)
5. Test by sending a sample POST with curl:

```bash
# Test Instagram webhook (will fail at Instagram API but verifies the webhook works)
curl -X POST https://n8n.yourdomain.com/webhook/markai/publish/instagram \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-header-auth-value" \
  -d '{"content_id":"test-123","caption":"Test","image_url":"https://example.com/test.jpg","instagram_account_id":"123","access_token":"fake"}'
```

---

## Adding More Platforms Later

For TikTok, X/Twitter, or any other platform:

1. Copy the Facebook workflow as a template
2. Change the webhook path to `markai/publish/{platform}`
3. Replace the HTTP Request node's URL and body format with the new platform's API
4. Keep the same callback pattern (POST to `/api/v1/webhooks/publish-result`)
5. In FastAPI, add the new platform to the `publish_checker.py` switch logic

The pattern is always the same: webhook in → platform API call → callback to FastAPI.
