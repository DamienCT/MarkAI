# VPS Deploy Command — Remove `--no-cache` Flag

## Context

The MarkAI VPS `/var/lib/containerd` grew to 129 GB (81% disk usage) because
Docker BuildKit cache accumulated without bound. On 2026-04-08 this was
reclaimed (157 GB → 43 GB used) and a weekly cleanup timer was installed on
the VPS:

- `/usr/local/sbin/docker-cleanup.sh` — runs `docker builder prune`, image
  prune, stopped-container prune
- `docker-cleanup.timer` — systemd timer, runs Sun 03:30 UTC with a 10 GB
  cache ceiling

**The VPS side is handled.** This doc is for the one remaining repo-level
fix: the manual deploy command used when pushing hot fixes from another
machine.

## The problem

In [VPS_SSH_TROUBLESHOOT.md](../VPS_SSH_TROUBLESHOOT.md) (and likely in other
handover notes), the deploy command is:

```bash
cd /var/www/markai
git fetch ado
git reset --hard ado/feature/enhancements
docker compose -f docker-compose.yml -f docker-compose.vps.yml build --no-cache backend agents frontend
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

`--no-cache` forces BuildKit to rebuild every layer from scratch every time.
Each rebuild writes new cache blobs that BuildKit *never evicts on its own*.
Over 2 weeks of frequent deploys this produced 120+ GB of cache.

`scripts/vps-redeploy.sh` does **not** use `--no-cache` — it's already
correct. This fix only applies to ad-hoc manual deploy commands in docs.

## The fix

### 1. Update [VPS_SSH_TROUBLESHOOT.md](../VPS_SSH_TROUBLESHOOT.md)

Find the "Pending VPS deployments" section (around line 128-145) and replace
the deploy command block with:

```bash
cd /var/www/markai
git fetch ado
git reset --hard ado/feature/enhancements
docker compose -f docker-compose.yml -f docker-compose.vps.yml build backend agents frontend
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

(Just remove `--no-cache`. Everything else stays.)

### 2. Search the repo for other occurrences

```bash
grep -rn "build --no-cache" --include="*.md" --include="*.sh" --include="*.yml"
```

For each hit:
- **In docs (`.md` files):** remove `--no-cache` unless the doc is specifically
  about rebuilding after a Dockerfile base image change.
- **In scripts (`.sh` files):** same — remove unless there's a justified
  comment explaining why it's needed.
- **In CI/compose files:** leave alone, review case by case.

### 3. Prefer `scripts/vps-redeploy.sh`

The canonical deploy path is `bash /var/www/markai/scripts/vps-redeploy.sh`.
It handles env vars, pg_dump backup, build, and restart in one shot — without
`--no-cache`. Any handover doc should point to this script first, with raw
`docker compose` commands only as a fallback for debugging.

## When `--no-cache` IS legitimate

Keep it (with a comment explaining why) only in these cases:
- Immediately after changing a base image pin in a Dockerfile (e.g.
  `FROM python:3.12-slim` → `3.13-slim`)
- After modifying system packages in the Dockerfile that apt might cache
- When debugging a "works on my machine" issue where cache may be hiding a bug

In all other cases, BuildKit's layer reuse is safe and ~10× faster.

## How to verify the VPS cleanup stayed stable

After merging this, check that disk usage isn't climbing back up. From any
machine with SSH access:

```bash
ssh markai 'df -h / && docker system df'
```

Expected steady state:
- Disk `/` at 20–35% used
- `Build Cache` under 10 GB
- `Images` around 15–20 GB

If `Build Cache` grows above 10 GB between weekly runs, the cron is doing its
job but the deploy frequency is high — consider reducing `OnCalendar` in
`/etc/systemd/system/docker-cleanup.timer` from weekly to every 3 days.

## Log location

The cleanup timer writes to `/var/log/docker-cleanup.log` on the VPS. Check
it after the first Sunday run to confirm:

```bash
ssh markai 'tail -30 /var/log/docker-cleanup.log'
```

## Summary

| Change | Where | Status |
|---|---|---|
| Reclaim 114 GB of BuildKit cache | VPS | ✅ done 2026-04-08 |
| Install `/usr/local/sbin/docker-cleanup.sh` | VPS | ✅ done |
| Enable `docker-cleanup.timer` (weekly Sun 03:30 UTC) | VPS | ✅ done |
| Auto-remove dead exited containers | VPS (via timer) | ✅ done |
| Remove `--no-cache` from deploy docs | repo | ⬜ **this PR** |
| Point all handover docs to `scripts/vps-redeploy.sh` | repo | ⬜ **this PR** |
