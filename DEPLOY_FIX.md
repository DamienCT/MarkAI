# VPS Deploy — All Phases + Full Audit

```bash
cd /var/www/markai
git pull origin main

# DB migrations (Phases 1-4)
docker exec -it markai-postgres psql -U markai -d markai -c "
  ALTER TABLE brands ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'active';
  ALTER TABLE brands ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;
  ALTER TABLE brands ADD COLUMN IF NOT EXISTS activation_started_at TIMESTAMPTZ;
  UPDATE brands SET status = 'active', onboarding_completed_at = created_at WHERE is_active = true;
  INSERT INTO app_settings (key, value) VALUES ('content_generation_days_ahead', '7') ON CONFLICT (key) DO NOTHING;
"

# DB migrations (v2 Audit — agent_runs FK constraints)
docker exec -it markai-postgres psql -U markai -d markai -c "
  UPDATE agent_runs SET brand_id = (SELECT id FROM brands LIMIT 1) WHERE brand_id IS NULL;
  ALTER TABLE agent_runs ALTER COLUMN brand_id SET NOT NULL;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_brand_id_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_prompt_version_id_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_prompt_version_id_fkey FOREIGN KEY (prompt_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_initiated_by_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_initiated_by_fkey FOREIGN KEY (initiated_by) REFERENCES users(id) ON DELETE SET NULL;
"

# DB migrations (v3 Audit — users table default)
docker exec -it markai-postgres psql -U markai -d markai -c "
  ALTER TABLE users ALTER COLUMN is_active SET DEFAULT FALSE;
"

# Rebuild ALL services (backend + frontend + agents all changed)
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

## What changed

**Phase 1 — Pipeline Fundamentals:**
- Channel filtering: content only for enabled channels
- Status transitions: queued→working→in_review (were stuck)
- Sequential processing: 1 content item at a time, nearest first
- Onboarding: competitors check via API
- Days ahead setting in Settings UI

**Phase 2 — Strategy & Calendar:**
- Year-long Content Calendar Strategy Document
- Even date distribution (1 post/channel/day)
- Calendar view: brand colors, channel badges, brand names
- ContentCard shows brand context

**Phase 3 — Intelligence & Reports:**
- 4 formatted report cards (Research, Strategy, Plan, Calendar Strategy)
- Trends endpoint returns real theme data (no more nan%)
- Research loads existing DB competitors
- Report detail pages render all 4 types with proper formatting

**Phase 4 — Scheduler:**
- get_app_setting() reads from DB at runtime
- Morning job daily content top-up within days_ahead window

**Phase 5 — v1 Audit (17 fixes):**
- CRITICAL: Fixed `current_depth` NameError crash in worker sequential content chaining
- CRITICAL: Fixed webhook endpoint open when N8N_WEBHOOK_SECRET not configured
- CRITICAL: All workflow graphs now have conditional failure routing on every node
- Fixed brand activation: is_active=True during activating state
- Fixed publish_checker: status set to "publishing" BEFORE dispatch
- Fixed adapt_platforms fallback: ALL_CHANNELS → ["instagram"]
- Fixed calendar_item_ids sorted by scheduled_at ASC
- Fixed User model is_active default: True → False
- Fixed Notification model field sizes to match DB schema
- Fixed bidirectional is_active/status sync
- Fixed competitors check uses API-fetched state variable
- Fixed research node error returns include status="failed"

**Phase 6 — v2 Deep Audit (28 fixes):**
- CRITICAL: Backend production startup validates Azure AD credentials
- CRITICAL: BrandForm removed is_active:true (prevented silent activation during edits)
- CRITICAL: agent_runs FK constraints (brand_id NOT NULL CASCADE, SET NULL on others)
- CRITICAL: VALID_TRANSITIONS includes "publishing" state + failed→scheduled retry
- CRITICAL: Worker catches GraphInterrupt → paused_for_review (was crashing)
- CRITICAL: Chain depth off-by-one fixed (prevents infinite adaptation loop)
- CRITICAL: Path traversal protection on /api/v1/files/ endpoint
- HIGH: Product image sourcing uses product_ids from calendar items
- HIGH: load_strategy parses JSON string from output_payload
- HIGH: Approval endpoint accepts "rejected" status
- HIGH: bc_locations and image_urls model types corrected
- MEDIUM: Logo dimension guards, coordinate clipping
- MEDIUM: Timezone-aware calendar ID sorting
- MEDIUM: Qdrant collection creation race condition handled
- MEDIUM: Frontend env var validation, competitors fetched on load

**Phase 7 — v3 Convergence Audit (14 fixes, converged in 3 passes):**
- users table is_active DEFAULT FALSE in init.sql (was TRUE, mismatched model)
- product_intel graph: added _check_failed + conditional edges
- ALL chat_completion() calls across ALL 7 workflows wrapped in try/except (21 nodes total)
- agent_run model/schema: brand_id required (not optional)
- morning_jobs: removed invalid 'planned' status from query
- Frontend ContentStatus: added "publishing" to type union
