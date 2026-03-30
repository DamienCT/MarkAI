# Fresh Deploy — MARKAI Full Stack

This deploy wipes all existing data and starts fresh with the latest codebase.

## Pre-flight Checklist

Before deploying, ensure your `.env` on the VPS has:

```
AZURE_AD_TENANT_ID=...
AZURE_AD_CLIENT_ID=...
AZURE_AD_CLIENT_SECRET=...
OPENAI_API_KEY=...
GEMINI_API_KEY=...
LITELLM_MASTER_KEY=...
MARKAI_DOMAIN=...
NEXTAUTH_SECRET=...
NEXTAUTH_URL=https://${MARKAI_DOMAIN}
FRONTEND_URL=https://${MARKAI_DOMAIN}
```

## Deploy Steps

```bash
cd /var/www/markai
git pull origin main

# Stop all services
docker compose -f docker-compose.yml -f docker-compose.vps.yml down

# Remove old data volumes (FRESH START — wipes DB, vectors, stored files, cache)
docker volume rm markai_pgdata markai_qdrant_data markai_minio_data markai_valkey_data markai_nats_data || true

# Rebuild all application services
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents

# Start everything (init.sql runs automatically on fresh postgres)
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d

# Wait for postgres to initialize
sleep 15

# Verify DB schema has new calendar_items columns
docker exec markai-postgres psql -U markai -d markai -c 'SELECT column_name FROM information_schema.columns WHERE table_name = '\''calendar_items'\'' AND column_name IN ('\''pillar'\'', '\''theme'\'', '\''target_audience'\'', '\''content_brief'\'') ORDER BY column_name;'

# Verify model categories (should show 5: text, text-fast, image, embedding, vision)
docker exec markai-postgres psql -U markai -d markai -c 'SELECT slug FROM ai_model_categories ORDER BY slug;'

# Verify all services healthy
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
```

## Post-Deploy Verification

1. **Frontend loads** — visit `https://${MARKAI_DOMAIN}`, sign in via Azure AD
2. **Providers page** — `/providers` shows 5 model categories with active selections
3. **Create a brand** — complete onboarding (name, description, tone, logo, channels)
4. **Activate** — triggers research → strategy → planning → content pipeline
5. **System page** — `/system` shows all services green

## What's Included (Latest)

1. **BrandIntelligence** — consolidated context object for all AI workflows
2. **Enriched prompts** — competitors with threat levels, gaps with impact/effort, personas with content preferences
3. **Enriched strategy** — brand archetype, 12-month themes with weekly sub-themes, audience-persona cross-reference
4. **Enriched planning** — campaign target metrics, calendar items with pillar/theme/audience/brief/visual direction, dedup
5. **Enriched content** — full positioning + pillar + audience + strategy doc excerpt + dedup + learning from top performers
6. **DB schema** — calendar_items: pillar, theme, target_audience, weekly_sub_theme, content_brief, visual_direction, cta_type
7. **Token budgets** — strategy doc: 16384, calendar: 16384, themes: 8192, hook: 256, caption: 2048
8. **GPT-5.4** — all models upgraded, zero hardcoded model references in executable code
9. **Dynamic model resolution** — all LLM/image calls resolve from admin-selected models via `/providers`
10. **Audit fixes** — workflow graph error routing on all final nodes, schema size mismatches corrected, unused model categories cleaned up
