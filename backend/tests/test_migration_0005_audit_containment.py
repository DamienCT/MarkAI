"""Regression guards for the 0005 audit-containment DDL (N-10, N-16, N-17).

Text-level checks on purpose: they pin the contract that db/init.sql (fresh
installs) and alembic 0005 (prod convergence) carry the SAME schema changes,
without needing a live Postgres in the test environment.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SQL = (REPO_ROOT / "db" / "init.sql").read_text(encoding="utf-8")
MIGRATION = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "0005_audit_containment.py"
).read_text(encoding="utf-8")
ENV_PY = (REPO_ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")


def _adaptations_check(sql: str) -> str:
    match = re.search(
        r"CREATE TABLE adaptations.*?^\);", sql, re.DOTALL | re.MULTILINE
    )
    assert match, "adaptations table not found in init.sql"
    return match.group(0)


def test_init_sql_adaptations_check_allows_applied_and_rejected():
    """N-10: apply/reject writes must not violate the status CHECK."""
    table = _adaptations_check(INIT_SQL)
    for status in ("'applied'", "'rejected'", "'proposed'", "'auto_applied'"):
        assert status in table, f"adaptations CHECK missing {status}"


def test_migration_widens_adaptations_check_with_same_statuses():
    for status in ("'applied'", "'rejected'", "'proposed'", "'auto_applied'"):
        assert status in MIGRATION, f"0005 CHECK swap missing {status}"
    # The guard must probe 'rejected', never 'applied' ('auto_applied' would
    # substring-match it and skip the swap on un-converged databases).
    assert "LIKE '%rejected%'" in MIGRATION
    assert "LIKE '%applied%'" not in MIGRATION


def test_engagement_index_identical_in_init_sql_and_migration():
    """N-17: the index definition must exist in BOTH schema authorities."""
    index_cols = "ON engagement_metrics (content_id, fetched_at DESC)"
    assert f"CREATE INDEX idx_engagement_metrics_content_fetched {index_cols}" in INIT_SQL
    assert "CREATE INDEX IF NOT EXISTS idx_engagement_metrics_content_fetched" in MIGRATION
    assert index_cols in MIGRATION


def test_new_tables_and_column_in_both_authorities():
    for text in (INIT_SQL, MIGRATION):
        assert "system_flags" in text
        assert "webhook_events" in text
    assert "metadata            JSONB NOT NULL DEFAULT '{}'" in INIT_SQL.split(
        "CREATE TABLE campaigns"
    )[0], "products.metadata missing from init.sql products table"
    assert (
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'"
        in MIGRATION
    )


def test_system_flags_created_before_updated_at_trigger_loop():
    """Fresh installs must give system_flags the catch-all updated_at trigger."""
    assert "CREATE TABLE system_flags" in INIT_SQL
    assert INIT_SQL.index("CREATE TABLE system_flags") < INIT_SQL.index(
        "FUNCTION update_updated_at_column"
    )


def test_migration_chains_after_0004():
    assert 'revision = "0005_audit_containment"' in MIGRATION
    assert 'down_revision = "0004_brand_model_profiles"' in MIGRATION


def test_env_py_guards_autogenerate_drops():
    """N-16: reflected-only objects must be excluded, not dropped."""
    assert "def include_object(" in ENV_PY
    assert "brand_model_profiles" in ENV_PY, "guard comment must name the table at risk"
    # The hook must be wired into BOTH offline and online configure calls.
    assert ENV_PY.count("include_object=include_object") == 2
    assert "if reflected and compare_to is None" in ENV_PY
