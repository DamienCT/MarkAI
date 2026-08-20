-- 2026-08-20: analytics latest-snapshot fix + evaluation adaptations fix
--
-- Apply manually on prod (init.sql only runs on a fresh database):
--   docker compose exec -T postgres psql -U markai -d markai < db/migrations/2026-08-20_analytics_and_adaptations.sql
--
-- CREATE INDEX CONCURRENTLY cannot run inside a transaction block — run this
-- file with autocommit (plain psql, no -1 / BEGIN).

-- Serves the latest-snapshot-per-content aggregations
-- (DISTINCT ON (content_id) ... ORDER BY content_id, fetched_at DESC)
-- added to backend analytics and agents performance queries.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_engagement_metrics_content_fetched ON engagement_metrics (content_id, fetched_at DESC);
