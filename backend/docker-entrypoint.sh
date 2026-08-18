#!/bin/sh
# Run DB migrations, then start the API.
# - Databases that predate Alembic (prod, or fresh installs whose schema came
#   from db/init.sql) are stamped with the baseline revision first.
# - alembic upgrade head is idempotent; revision 0002 converges hand-drifted
#   schemas and no-ops where objects already exist.
set -e

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}/${POSTGRES_DB}}"

has_alembic_version=$(python - <<'PY'
import asyncio
import os

import asyncpg


async def main() -> None:
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        exists = await conn.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    finally:
        await conn.close()
    print("yes" if exists else "no")


asyncio.run(main())
PY
)

if [ "$has_alembic_version" = "no" ]; then
    echo "[entrypoint] No alembic_version table — stamping baseline"
    alembic stamp 0001_baseline
fi

echo "[entrypoint] Running alembic upgrade head"
alembic upgrade head

exec "$@"
