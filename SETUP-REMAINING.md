# MARKAI — What's Left for You to Set Up

**Generated:** March 24, 2026
**Status:** Application is 95% code-complete. Below is everything you need to configure/do before going live.

---

## 1. Environment Variables to Fill In (.env)

Copy `.env.example` to `.env` and fill in these values. Items marked with a checkmark are already filled in.

### Already Configured
- [x] `MARKAI_DOMAIN` — `markai.srv1191974.hstgr.cloud`
- [x] `SECRET_KEY`
- [x] `AZURE_AD_TENANT_ID` / `CLIENT_ID` / `CLIENT_SECRET`
- [x] `NEXTAUTH_URL` / `NEXTAUTH_SECRET`
- [x] `FABRIC_TENANT_ID` / `CLIENT_ID` / `CLIENT_SECRET`
- [x] `FABRIC_LAKEHOUSE_NAME` — `lh_bronze`
- [x] `OPENAI_API_KEY`
- [x] `BC_TABLE_ITEMS` / `ITEM_CATEGORIES` / `VENDORS` / `ITEM_LEDGER_ENTRIES`

### Still Need to Fill In
- [ ] `FABRIC_SQL_ENDPOINT` — Set to: `tpulqmzpboyufnm4qnn5bqwohq-dzkh3kllt6ou7ej4qc4lggg7fa.datawarehouse.fabric.microsoft.com`
- [ ] `POSTGRES_PASSWORD` — Change from `change-me` to a strong password
- [ ] `MINIO_SECRET_KEY` — Change from `change-me` to a strong password
- [ ] `LITELLM_MASTER_KEY` — Change from default to a random key (e.g. `sk-markai-<random>`)
- [ ] `N8N_WEBHOOK_BASE` — Your n8n instance's webhook URL (e.g. `https://n8n.srv1191974.hstgr.cloud/webhook`)
- [ ] `N8N_WEBHOOK_SECRET` — Random string shared between FastAPI and n8n for callback auth
- [ ] `FRONTEND_URL` — `https://markai.srv1191974.hstgr.cloud` (for CORS restriction)
- [ ] `TEAMS_WEBHOOK_URL` — Create an incoming webhook in your Microsoft Teams channel
- [ ] `META_ACCESS_TOKEN` — Long-lived Facebook/Instagram page token
- [ ] `META_PAGE_ID` — Your Facebook page ID
- [ ] `META_INSTAGRAM_ACCOUNT_ID` — Your Instagram business account ID
- [ ] `LINKEDIN_ACCESS_TOKEN` — LinkedIn OAuth token
- [ ] `LINKEDIN_ORG_ID` — Your LinkedIn organization URN
- [ ] `LANGCHAIN_API_KEY` — (Optional) LangSmith API key for agent tracing

---

## 2. Microsoft Entra ID Setup

### App Registration for MARKAI SSO (already partially done)
- [x] App registered with Client ID `1d8c982d-da50-4885-b7fe-598b651b158c`
- [ ] **Add redirect URI**: `https://markai.srv1191974.hstgr.cloud/api/auth/callback/azure-ad`
- [ ] **API permissions**: Ensure `User.Read` and `openid`, `profile`, `email` scopes are granted
- [ ] **Admin consent**: Grant admin consent for Chemtech Group tenant

### App Registration for Fabric (already partially done)
- [x] App registered with Client ID `47d43367-a8d9-4d61-9c9a-1678a508ebc7`
- [x] Service principal has Admin role on Chemtech Medallion workspace
- [ ] **Verify**: Service principal can query SQL endpoint (already confirmed working)

---

## 3. Microsoft Teams Webhook

1. Go to the Teams channel where you want MARKAI alerts
2. Click **...** → **Connectors** → **Incoming Webhook**
3. Name it "MARKAI Alerts", add an icon
4. Copy the webhook URL to `TEAMS_WEBHOOK_URL` in `.env`

---

## 4. n8n Social Publishing Workflows

You need 3 webhook workflows in your n8n instance at `https://n8n.srv1191974.hstgr.cloud`:

### Workflow 1: Instagram Publish
- **Trigger**: Webhook at `/markai/publish/instagram`
- **Action**: Receive payload → Upload image to Instagram via Graph API → POST result back to `https://api.markai.srv1191974.hstgr.cloud/api/v1/webhooks/publish-result`
- **Callback payload**: `{ content_id, platform: "instagram", status: "published"|"failed", platform_post_id, published_at, error }`
- **Include header**: `X-Webhook-Secret: <your N8N_WEBHOOK_SECRET value>`

### Workflow 2: Facebook Publish
- **Trigger**: Webhook at `/markai/publish/facebook`
- **Action**: Same pattern, Facebook Graph API page post
- **Callback**: Same endpoint with `platform: "facebook"`

### Workflow 3: LinkedIn Publish
- **Trigger**: Webhook at `/markai/publish/linkedin`
- **Action**: Same pattern, LinkedIn API UGC post
- **Callback**: Same endpoint with `platform: "linkedin"`

### Inbound payload from MARKAI:
```json
{
  "content_id": "uuid",
  "caption": "Post text...",
  "image_url": "https://minio-url/image.jpg",
  "hashtags": ["tag1", "tag2"],
  "access_token": "platform-token",
  "page_id": "...",
  "instagram_account_id": "...",
  "org_id": "..."
}
```

---

## 5. Social Platform API Setup

### Meta (Instagram + Facebook)
1. Go to [developers.facebook.com](https://developers.facebook.com)
2. Create/use an app with **Instagram Graph API** and **Pages API** permissions
3. Generate a long-lived page access token (60-day, auto-renewed by your app)
4. Get your Page ID and Instagram Business Account ID
5. Set `META_ACCESS_TOKEN`, `META_PAGE_ID`, `META_INSTAGRAM_ACCOUNT_ID` in `.env`

### LinkedIn
1. Go to [linkedin.com/developers](https://linkedin.com/developers)
2. Create an app with **Share on LinkedIn** and **Marketing Developer Platform** products
3. Generate an OAuth access token with `w_member_social` and `w_organization_social` scopes
4. Get your organization URN (format: `urn:li:organization:12345`)
5. Set `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_ORG_ID` in `.env`

---

## 6. DNS & Traefik (Production)

### DNS Records Needed
Point these to your server IP:
- `markai.srv1191974.hstgr.cloud` → Frontend
- `api.markai.srv1191974.hstgr.cloud` → Backend API
- `n8n.srv1191974.hstgr.cloud` → n8n (already set up)
- `grafana.markai.srv1191974.hstgr.cloud` → Grafana dashboards (optional)

### Traefik TLS
Traefik is configured for Let's Encrypt auto-TLS. On first `docker compose up`, it will request certificates automatically. Ensure port 443 is open on the server.

---

## 7. First Launch Checklist

```bash
# 1. SSH to your server
# 2. Clone the repo and cd into it
# 3. Copy and fill .env
cp .env.example .env
nano .env  # fill in all values above

# 4. Start all services
docker compose up -d

# 5. Wait for postgres to be ready (~30s)
docker compose logs -f postgres  # wait for "database system is ready"

# 6. Check all services are healthy
docker compose ps

# 7. Run AI model discovery (populates available models)
curl -X POST https://api.markai.srv1191974.hstgr.cloud/api/v1/providers/discover \
  -H "Authorization: Bearer <your-token>"

# 8. Open the admin portal
# https://markai.srv1191974.hstgr.cloud
# Login with your Entra ID account (Damien@chemtech.mu)

# 9. First things to do in the portal:
#    a. Go to Providers → Select active AI models per category
#    b. Go to Brands → Create your first brand → Link BC company + locations
#    c. Trigger a product sync from the Products page
#    d. Check System page for service health
```

---

## 8. Post-Launch Tasks (Can Do Later)

### Short Term
- [ ] **Generate Alembic migration**: `cd backend && alembic revision --autogenerate -m "initial"` — needed for future schema changes
- [ ] **Set up Grafana dashboards**: Pre-provisioned datasources are ready, create dashboards for content pipeline metrics
- [ ] **Configure LangSmith**: Set `LANGCHAIN_API_KEY` for agent workflow tracing/debugging
- [ ] **Test n8n workflows**: Publish test content to each platform, verify callback works

### Medium Term
- [ ] **MinIO migration planning**: MinIO was archived in February 2026. Plan migration to RustFS or Garage (S3-compatible). Current MinIO works fine but won't get security patches
- [ ] **Upgrade planning**: LangGraph 1.1 GA is available (we use 0.4+), Next.js 16.2 has breaking changes. Both are "nice to have" upgrades, not urgent
- [ ] **CI/CD pipeline**: Set up GitHub Actions for automated testing and Docker builds
- [ ] **Rate limiting**: Add slowapi or similar to protect API endpoints
- [ ] **Backup strategy**: Set up PostgreSQL pg_dump cron or use Fabric/Azure Backup

---

## 9. Architecture Quick Reference

| Service | Internal URL | External URL | Port |
|---------|-------------|-------------|------|
| Frontend | http://frontend:3000 | https://markai.srv1191974.hstgr.cloud | 3000 |
| Backend API | http://backend:8000 | https://api.markai.srv1191974.hstgr.cloud | 8000 |
| PostgreSQL | postgres:5432 | localhost:5433 | 5432 |
| Qdrant | qdrant:6333 | localhost:6333 | 6333 |
| MinIO | minio:9000 | localhost:9000 (API), 9001 (Console) | 9000 |
| Valkey | valkey:6379 | localhost:6381 | 6379 |
| NATS | nats:4222 | localhost:4222 | 4222 |
| LiteLLM | litellm:4000 | localhost:4000 | 4000 |
| n8n | n8n:5678 | https://n8n.srv1191974.hstgr.cloud | 5678 |
| Browser Worker | browser-worker:8001 | (internal only) | 8001 |
| Notifications | notifications:8002 | (internal only) | 8002 |
| Grafana | grafana:3000 | https://grafana.markai.srv1191974.hstgr.cloud | 3001 |
| Prometheus | prometheus:9090 | localhost:9090 | 9090 |
| Loki | loki:3100 | localhost:3100 | 3100 |
| OTEL Collector | otel-collector:4317 | localhost:4317 | 4317 |

---

## 10. Known Limitations & Future Considerations

| Item | Status | Notes |
|------|--------|-------|
| **MinIO archived** | Monitor | Works today, but plan migration to RustFS/Garage in Q2-Q3 2026 |
| **No automated tests** | Deferred | Test infrastructure ready, tests to be added in Cycle 2 |
| **No CI/CD** | Deferred | GitHub Actions pipeline to be added post-launch |
| **GPT-4o deprecation** | Handled | Model discovery cron picks up new models (GPT-4.1 available) |
| **OWASP Agentic AI** | Aware | New OWASP Top 10 for Agentic Applications applies to LangGraph workflows |
| **Soft deletes** | Deferred | Hard deletes used now; add soft delete pattern for compliance |
| **Rate limiting** | Deferred | Not critical for internal use, add before public exposure |
