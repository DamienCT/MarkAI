# Channel Credentials — per-brand publishing setup

Since 2026-08-22 every channel publishes **natively from the backend** (n8n
removed). Credentials live **per brand** in the UI — **Brand → Channels** —
stored under `brand_guidelines.channels.<channel>.<field>`; nothing
channel-specific goes into `.env` (the remaining `*_TOKEN`/`*_KEY` env vars
are optional global fallbacks only).

How the form behaves:

- Secret-like fields (tokens, secrets, passwords, webhook URLs) are
  **write-only**: the API strips them from reads, so the form never shows a
  saved value. A configured channel shows the placeholder
  "configured — enter new value to replace"; type a new value to replace,
  leave blank to keep the stored one.
- A channel without credentials **fails closed**: publishes to it are
  recorded `failed` with an actionable error naming the missing setup —
  never a silent queue, never a fake success.

## X (Twitter)

Fields in Brand → Channels → X: `consumer_key`, `consumer_secret`,
`access_token`, `access_token_secret`, `handle` (optional).

Where to get them: [developer.x.com](https://developer.x.com) → create an
app with **Read and Write** permissions, on an API tier that can
`POST /2/tweets` (the free tier has a low monthly write cap; check current
limits). Under the app's *Keys and tokens*: the **Consumer Keys** pair gives
`consumer_key`/`consumer_secret`; generate the **Access Token and Secret**
for the account that should post (must be created *after* setting Read and
Write) to get `access_token`/`access_token_secret`. Requests are signed with
OAuth 1.0a user context — all four values are required.

## TikTok

Fields in Brand → Channels → TikTok: `client_key`, `client_secret`,
`access_token`, `refresh_token` (optional but strongly recommended),
`handle` (optional).

Where to get them: [developers.tiktok.com](https://developers.tiktok.com) →
create an app with the **Content Posting API** product and the
`video.publish` (content posting) scope, then complete the OAuth flow for
the brand's TikTok account to obtain the access/refresh tokens.

Notes:

- TikTok access tokens live **24 hours**. Provide the `refresh_token` and
  the backend refreshes automatically (new tokens are written back to the
  brand's channel config); without it, expect daily manual re-entry.
- Unaudited apps can only post **SELF_ONLY** (visible to the account owner)
  — the default privacy level. Public posting requires TikTok's app audit;
  after approval the channel's `privacy_level` config can be raised.
- TikTok is video-only: image content fails with "TikTok requires video
  content".

## Website / Blog (WordPress)

Fields in Brand → Channels → Website / Blog: `base_url`, `username`,
`app_password`, `platform` (optional, defaults to `wordpress` — the only
supported driver today).

Where to get them: on the WordPress site, log in as a user who can publish
posts → **Users → Profile → Application Passwords** → create one named e.g.
"MarkAI" and copy the generated password (spaces are fine). `base_url` is
the site root (e.g. `https://blog.example.com`); the backend posts via the
REST API (`/wp-json/wp/v2/...`) with Basic auth, uploading the branded image
as featured media. Application passwords require the site to be served over
HTTPS.

If left unconfigured, blog items stay available in Content Studio for
manual publishing.

## Microsoft Teams

Field in Brand → Channels → Teams: `webhook_url`.

Where to get it: in the target Teams channel → **... → Connectors →
Incoming Webhook** (or Workflows-based incoming webhook) → create and copy
the URL. **The URL itself is the credential** — treat it like a password
(it is write-only in the UI and never logged).

## Instagram / Facebook (Meta)

Fields: Instagram — `handle`, `account_id`, `access_token`;
Facebook — `page_id`, `access_token`.

Where: [developers.facebook.com](https://developers.facebook.com) → app with
Instagram Graph API + Pages API permissions → long-lived **page** access
token; `account_id` is the Instagram Business Account ID, `page_id` the
Facebook Page ID.

## LinkedIn

Fields: `org_id`, `access_token`, `client_id`, `client_secret`.

Where: [linkedin.com/developers](https://linkedin.com/developers) → app with
the Share on LinkedIn / Marketing products → OAuth token with
`w_organization_social`; `org_id` from the organization URN
(`urn:li:organization:<id>`). Client ID/Secret enable the token-status check
shown in the channel panel.

## YouTube

Fields: `channel_id`, `api_key` (per-brand OAuth client/refresh-token fields
are also supported, falling back to the global `YOUTUBE_*` env vars).

Where: Google Cloud Console → project with **YouTube Data API v3** enabled;
uploads require an OAuth client (client ID/secret + refresh token for the
channel's Google account).
