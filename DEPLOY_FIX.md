# Deploy MARKAI to VPS

## Prerequisites
- SSH access to the VPS
- Docker and Docker Compose installed
- Traefik reverse proxy running on the VPS

## Deploy Commands

```bash
ssh your-vps

cd /var/www/markai
git pull origin main

# Run DB migrations
docker exec -it markai-postgres psql -U markai -d markai -c "
  -- Brand lifecycle columns
  ALTER TABLE brands ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'active';
  ALTER TABLE brands ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;
  ALTER TABLE brands ADD COLUMN IF NOT EXISTS activation_started_at TIMESTAMPTZ;
  UPDATE brands SET status = 'active', onboarding_completed_at = created_at WHERE is_active = true;

  -- App settings
  INSERT INTO app_settings (key, value) VALUES ('content_generation_days_ahead', '7') ON CONFLICT (key) DO NOTHING;

  -- Users default inactive (pending approval)
  ALTER TABLE users ALTER COLUMN is_active SET DEFAULT FALSE;

  -- agent_runs FK constraints
  UPDATE agent_runs SET brand_id = (SELECT id FROM brands LIMIT 1) WHERE brand_id IS NULL;
  ALTER TABLE agent_runs ALTER COLUMN brand_id SET NOT NULL;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_brand_id_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_prompt_version_id_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_prompt_version_id_fkey FOREIGN KEY (prompt_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_initiated_by_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_initiated_by_fkey FOREIGN KEY (initiated_by) REFERENCES users(id) ON DELETE SET NULL;
"

# Rebuild and restart all services
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

## Verify Deployment

```bash
# Check all services are healthy
docker compose -f docker-compose.yml -f docker-compose.vps.yml ps

# Check backend health
curl -sf https://api.markai.srv1191974.hstgr.cloud/health

# Check frontend loads
curl -sf -o /dev/null -w '%{http_code}' https://markai.srv1191974.hstgr.cloud/

# Check logs for errors
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --tail=50 backend agents frontend
```
