# Fresh Deploy — World-Class Content Engine Upgrade

This deploy wipes all existing data and starts fresh with the enriched pipeline.

```bash
cd /var/www/markai
git pull origin main

# Stop all services
docker compose -f docker-compose.yml -f docker-compose.vps.yml down

# Remove old database volume (FRESH START)
docker volume rm markai_pgdata || true

# Rebuild all services
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents

# Start services (init.sql runs automatically on fresh DB)
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d

# Wait for postgres to initialize
sleep 10

# Verify DB has new columns
docker exec -it markai-postgres psql -U markai -d markai -c "\d calendar_items" | grep -E "pillar|theme|target_audience|content_brief"
```

## What Changed

**World-class content engine upgrade — 8 phases:**

1. **BrandIntelligence package** — single consolidated context object for all AI workflows (brand + research + strategy + planning + products + engagement history)
2. **Enriched research prompts** — competitors with positioning/strengths/weaknesses/threat levels, gaps with impact/effort/timeline/KPIs, personas with content preferences/buying triggers/engagement times
3. **Enriched strategy prompts** — brand archetype, competitive differentiation matrix, pillar audience alignment, 12-month themes with weekly sub-themes, audience cross-referenced with research personas
4. **Enriched planning prompts** — campaign target metrics, calendar items with pillar/theme/audience/brief/visual direction, dedup against existing items, strategy document 16K tokens
5. **Enriched content prompts** — full positioning + pillar + audience + strategy doc month excerpt + recent posts dedup + top performing content learning + brand colors in image prompts
6. **DB schema** — calendar_items gains: pillar, theme, target_audience, weekly_sub_theme, content_brief, visual_direction, cta_type
7. **Token budgets** — strategy doc: 16384, calendar: 16384, themes: 8192, hook: 256, caption: 2048
8. **Frontend** — enriched report rendering for competitors, gaps, personas, positioning, pillars, calendar items
9. **GPT-5.4** — all fallback models upgraded, legacy models removed from LiteLLM config
