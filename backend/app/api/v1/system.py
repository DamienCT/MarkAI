import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuditLog, ScheduledJobLog, User
from app.auth.permissions import role_has_access
from app.config import settings
from app.deps import get_current_user, get_db
from app.scheduler import scheduler

logger = logging.getLogger(__name__)

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    environment: str
    dependencies: dict[str, str] = {}


class JobInfo(BaseModel):
    id: str
    name: str
    next_run_time: str | None
    trigger: str


async def _check_postgres(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def _check_valkey() -> str:
    try:
        import redis.asyncio as redis
        from app.config import settings

        r = redis.Redis(host=settings.VALKEY_HOST, port=settings.VALKEY_PORT, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


async def _check_nats() -> str:
    try:
        from app.services import nats_service

        if nats_service._nc and nats_service._nc.is_connected:
            return "ok"
        return "disconnected"
    except Exception as exc:
        return f"error: {exc}"


async def _check_minio() -> str:
    try:
        from app.services import minio_service

        minio_service._client.list_buckets()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


@router.get("/health", response_model=HealthResponse)
async def health_check(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Authenticated health check endpoint with dependency status."""
    from app.config import settings

    deps: dict[str, str] = {}
    deps["postgres"] = await _check_postgres(db)
    deps["valkey"] = await _check_valkey()
    deps["nats"] = await _check_nats()
    deps["minio"] = await _check_minio()

    all_ok = all(v == "ok" for v in deps.values())

    return HealthResponse(
        status="healthy" if all_ok else "degraded",
        timestamp=datetime.now(timezone.utc).isoformat(),
        environment=settings.MARKAI_ENV,
        dependencies=deps,
    )


@router.get("/jobs", response_model=list[JobInfo])
async def list_scheduler_jobs(
    current_user: User = Depends(get_current_user),
):
    """List all registered APScheduler jobs."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    jobs = scheduler.get_jobs()
    return [
        JobInfo(
            id=job.id,
            name=job.name or job.id,
            next_run_time=(
                job.next_run_time.isoformat() if job.next_run_time else None
            ),
            trigger=str(job.trigger),
        )
        for job in jobs
    ]


@router.post("/jobs/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    """Manually trigger a scheduled job."""
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    job.modify(next_run_time=datetime.now(timezone.utc))
    return {"message": f"Job '{job_id}' triggered", "job_id": job_id}


@router.get("/audit-log")
async def get_audit_log(
    user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    action: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve audit log entries."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    stmt = (
        select(AuditLog)
        .offset(skip)
        .limit(limit)
        .order_by(AuditLog.created_at.desc())
    )
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "user_id": str(log.user_id) if log.user_id else None,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": str(log.entity_id) if log.entity_id else None,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "ip_address": str(log.ip_address) if log.ip_address else None,
            "user_agent": log.user_agent,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get("/job-log")
async def get_job_log(
    job_name: str | None = None,
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve scheduled job execution log."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    stmt = (
        select(ScheduledJobLog)
        .offset(skip)
        .limit(limit)
        .order_by(ScheduledJobLog.started_at.desc())
    )
    if job_name is not None:
        stmt = stmt.where(ScheduledJobLog.job_name == job_name)
    if status_filter is not None:
        stmt = stmt.where(ScheduledJobLog.status == status_filter)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "job_name": log.job_name,
            "job_type": log.job_type,
            "status": log.status,
            "started_at": log.started_at.isoformat(),
            "completed_at": log.completed_at.isoformat() if log.completed_at else None,
            "error_message": log.error_message,
            "details": log.details,
            "duration_ms": log.duration_ms,
        }
        for log in logs
    ]


@router.get("/services")
async def system_services(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return health/latency of each infrastructure service."""
    services = []

    # Postgres
    t0 = time.monotonic()
    try:
        await db.execute(text("SELECT 1"))
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "postgres", "status": "healthy", "latency_ms": latency})
    except Exception:
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "postgres", "status": "unhealthy", "latency_ms": latency})

    # Valkey
    t0 = time.monotonic()
    try:
        import redis.asyncio as redis

        r = redis.Redis(host=settings.VALKEY_HOST, port=settings.VALKEY_PORT, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "valkey", "status": "healthy", "latency_ms": latency})
    except Exception:
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "valkey", "status": "unhealthy", "latency_ms": latency})

    # NATS
    t0 = time.monotonic()
    try:
        from app.services import nats_service

        if nats_service._nc and nats_service._nc.is_connected:
            latency = round((time.monotonic() - t0) * 1000, 1)
            services.append({"name": "nats", "status": "healthy", "latency_ms": latency})
        else:
            latency = round((time.monotonic() - t0) * 1000, 1)
            services.append({"name": "nats", "status": "unhealthy", "latency_ms": latency})
    except Exception:
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "nats", "status": "unhealthy", "latency_ms": latency})

    # MinIO
    t0 = time.monotonic()
    try:
        from app.services import minio_service

        minio_service._client.list_buckets()
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "minio", "status": "healthy", "latency_ms": latency})
    except Exception:
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "minio", "status": "unhealthy", "latency_ms": latency})

    # Qdrant
    t0 = time.monotonic()
    try:
        from qdrant_client import QdrantClient

        qc = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=2)
        qc.get_collections()
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "qdrant", "status": "healthy", "latency_ms": latency})
    except Exception:
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "qdrant", "status": "unhealthy", "latency_ms": latency})

    # LiteLLM
    t0 = time.monotonic()
    try:
        import httpx

        async with httpx.AsyncClient(timeout=2) as client:
            headers = {}
            if settings.LITELLM_MASTER_KEY:
                headers["Authorization"] = f"Bearer {settings.LITELLM_MASTER_KEY}"
            resp = await client.get(f"{settings.LITELLM_BASE_URL}/health", headers=headers)
            status_str = "healthy" if resp.status_code == 200 else "unhealthy"
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "litellm", "status": status_str, "latency_ms": latency})
    except Exception:
        latency = round((time.monotonic() - t0) * 1000, 1)
        services.append({"name": "litellm", "status": "unhealthy", "latency_ms": latency})

    return services


@router.get("/scheduler/jobs")
async def list_scheduler_jobs_detail(
    current_user: User = Depends(get_current_user),
):
    """List all registered APScheduler jobs with their next run time."""
    jobs = scheduler.get_jobs()
    return [
        {
            "id": job.id,
            "name": job.name or job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        }
        for job in jobs
    ]


@router.get("/queues")
async def system_queues(
    current_user: User = Depends(get_current_user),
):
    """Return NATS JetStream stream info (name, message count, consumer count)."""
    try:
        from app.services import nats_service

        js = nats_service.get_jetstream()
        streams = []
        for stream_name in nats_service.STREAMS:
            try:
                stream_info = await js.stream_info(stream_name)
                streams.append({
                    "name": stream_name,
                    "messages": stream_info.state.messages,
                    "consumers": stream_info.state.consumer_count,
                })
            except Exception:
                streams.append({
                    "name": stream_name,
                    "messages": 0,
                    "consumers": 0,
                })
        return streams
    except Exception:
        return []
