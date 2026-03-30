# Redeploy — Full Verification Audit Fixes

```bash
cd /var/www/markai
git pull origin main

# DB migrations
docker exec -it markai-postgres psql -U markai -d markai -c "
  ALTER TABLE users ALTER COLUMN is_active SET DEFAULT FALSE;
  UPDATE agent_runs SET brand_id = (SELECT id FROM brands LIMIT 1) WHERE brand_id IS NULL;
  ALTER TABLE agent_runs ALTER COLUMN brand_id SET NOT NULL;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_brand_id_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_prompt_version_id_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_prompt_version_id_fkey FOREIGN KEY (prompt_version_id) REFERENCES prompt_versions(id) ON DELETE SET NULL;
  ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_initiated_by_fkey;
  ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_initiated_by_fkey FOREIGN KEY (initiated_by) REFERENCES users(id) ON DELETE SET NULL;
"

# Rebuild all services (backend + frontend + agents all changed)
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend frontend agents
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```
