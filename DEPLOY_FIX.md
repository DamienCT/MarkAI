# Fresh Deploy — MARKAI Full Stack

This deploy wipes all existing data and starts fresh with the latest codebase.

## Step 1 — Pull Latest Code

```bash
cd /var/www/markai
git pull origin main
```

## Step 2 — Tear Down Everything

```bash
cd /var/www/markai
docker compose -f docker-compose.yml -f docker-compose.vps.yml down
docker volume rm markai_pgdata markai_qdrant_data markai_minio_data markai_valkey_data markai_nats_data || true
```

## Step 3 — Rebuild and Start

```bash
cd /var/www/markai
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

## Step 4 — Wait and Verify

Wait 20 seconds for postgres to finish init.sql, then run each check separately.

```bash
sleep 20
```

Check all containers are running:

```bash
cd /var/www/markai
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps
```

Check postgres is up and schema is correct:

```bash
docker exec markai-postgres psql -U markai -d markai -c "SELECT count(*) FROM ai_model_categories"
```

Check backend is healthy:

```bash
docker logs markai-backend --tail 10
```

Check frontend is healthy:

```bash
docker logs markai-frontend --tail 10
```

Check agents are healthy:

```bash
docker logs markai-agents --tail 10
```

## Expected Results

- All containers show `Up` and `healthy` in `docker compose ps`
- `ai_model_categories` count returns **5** (text, text-fast, image, embedding, vision)
- Backend logs show `Uvicorn running on http://0.0.0.0:8000`
- Frontend logs show `Ready on http://0.0.0.0:3000`
- Agents logs show `Connected to NATS` or similar startup message

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
