#!/usr/bin/env python3
"""Remediate strategy runs the OLD worker mislabeled as 'completed'.

Containment runbook §10 (docs/SECURITY_CONTAINMENT_2026-08-21.md) as code.
Before the HITL safe-stop shipped (2026-08-21), a strategy graph hitting
interrupt() returned normally and the worker stamped the run 'completed' —
so get_latest_strategy (which filters status='completed') can serve an
UNAPPROVED, interrupt-shaped payload to downstream stages (N-09/P0-01).

Affected rows are identified by interrupt-shaped output: raw graph state
with a top-level 'pillars' key and no 'content_pillars' key (genuine
store_strategy artifact rows carry 'content_pillars' instead — see
agents/workflows/strategy/nodes.py::human_review). Runs parked by the NEW
worker are status='paused_for_review' and are never touched.

Dry-run by default: prints the candidate rows and changes nothing.
--apply re-statuses them to 'failed' with an explanatory error_message;
output_payload is preserved for forensics. Idempotent — remediated rows no
longer match the predicate. This is a DATA fix (UPDATE only, no DDL), so it
does not conflict with the "schema changes ride alembic" rule (§9).

Usage (VPS — the backend image does not ship scripts/, copy it in first):

    ssh markai
    # The backend image ships this file at /app/scripts/ (Dockerfile COPY).
    # Dry run — inspect candidates (uses the container's DATABASE_URL):
    docker exec markai-backend python /app/scripts/remediate_interrupted_runs.py
    # Eyeball every printed row, then apply only the confirmed ids:
    docker exec markai-backend python /app/scripts/remediate_interrupted_runs.py \
        --apply --id <run-id> [--id <run-id> ...]

Locally / elsewhere, pass the DSN explicitly:

    python backend/scripts/remediate_interrupted_runs.py --dsn postgresql://markai:...@localhost:5432/markai
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

import asyncpg

# Interrupt-shape predicate — keep in sync with runbook §10. The `?` here is
# the JSONB key-exists operator, not a placeholder (asyncpg uses $n).
#
# The real discriminator is the '__interrupt__' marker: the pre-HITL worker
# json.dumps'ed the raw graph result (default=str), so every mislabeled row
# carries it at top level — while a GENUINELY completed strategy run never
# does (and does carry human_review's 'human_approved'). 'pillars' alone
# matches every legitimate completion too, so it is only a sanity narrower.
CANDIDATE_PREDICATE = (
    "agent_type = 'strategy' "
    "AND status = 'completed' "
    "AND output_payload ? '__interrupt__' "
    "AND NOT output_payload ? 'human_approved'"
)

REMEDIATION_NOTE = (
    f"remediated {date.today().isoformat()} (containment runbook §10): "
    "interrupt-shaped output recorded as 'completed' by the pre-HITL worker "
    "— never approved by a human; output_payload preserved"
)


def resolve_dsn(cli_dsn: str | None) -> str:
    """--dsn wins; otherwise the backend's DATABASE_URL env. Fail closed."""
    dsn = cli_dsn or os.environ.get("DATABASE_URL", "")
    if not dsn:
        print(
            "ERROR: no DSN — pass --dsn or set DATABASE_URL "
            "(inside markai-backend it is already set).",
            file=sys.stderr,
        )
        sys.exit(2)
    # The backend's DATABASE_URL is SQLAlchemy-form; asyncpg wants plain
    # postgresql:// (same strip as backend/docker-entrypoint.sh).
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


async def run(dsn: str, apply: bool, only_ids: list[str] | None = None) -> None:
    conn = await asyncpg.connect(dsn)
    only_ids = only_ids or []
    try:
        rows = await conn.fetch(
            "SELECT id, brand_id, created_at, completed_at, "
            "left(output_payload::text, 160) AS payload_head "
            f"FROM agent_runs WHERE {CANDIDATE_PREDICATE} "
            "ORDER BY created_at"
        )
        if not rows:
            print("No mislabeled 'completed' strategy runs found — nothing to do.")
            return

        mode = "APPLY" if apply else "DRY RUN"
        print(f"[{mode}] {len(rows)} interrupt-shaped run(s) with status='completed':\n")
        for row in rows:
            print(f"  run_id:     {row['id']}")
            print(f"  brand_id:   {row['brand_id']}")
            print(f"  created_at: {row['created_at']}  completed_at: {row['completed_at']}")
            print(f"  payload:    {row['payload_head']}\n")

        if not apply:
            print(
                "Dry run — nothing changed. Eyeball each row above, then re-run "
                "with --apply (optionally --id <uuid> per approved row) to "
                "re-status them to 'failed'."
            )
            return

        # --apply still re-checks the predicate, and an --id allowlist makes
        # the eyeball-then-apply flow enforceable instead of advisory.
        if only_ids:
            updated = await conn.fetch(
                "UPDATE agent_runs SET status = 'failed', error_message = $1 "
                f"WHERE {CANDIDATE_PREDICATE} AND id = ANY($2::uuid[]) "
                "RETURNING id",
                REMEDIATION_NOTE,
                only_ids,
            )
        else:
            updated = await conn.fetch(
                "UPDATE agent_runs SET status = 'failed', error_message = $1 "
                f"WHERE {CANDIDATE_PREDICATE} RETURNING id",
                REMEDIATION_NOTE,
            )
        for row in updated:
            print(f"re-statused to 'failed': {row['id']}")
        print(
            f"\nDone — {len(updated)} run(s) re-statused; they can no longer "
            "satisfy get_latest_strategy. Re-run strategy for the affected "
            "brand(s) to produce a genuine approved strategy."
        )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Re-status interrupt-shaped strategy runs mislabeled 'completed' "
            "by the pre-HITL worker (runbook §10). Dry-run unless --apply."
        )
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Postgres DSN (default: the DATABASE_URL env var)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually re-status the candidate rows to 'failed' (default: dry run)",
    )
    parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        default=None,
        metavar="RUN_ID",
        help=(
            "restrict --apply to this run id (repeatable) — makes the "
            "eyeball-then-apply flow enforceable"
        ),
    )
    args = parser.parse_args()

    dsn = resolve_dsn(args.dsn)
    try:
        asyncio.run(run(dsn, apply=args.apply, only_ids=args.ids))
    except (asyncpg.PostgresError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
