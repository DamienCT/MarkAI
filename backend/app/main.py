import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.router import api_router
from app.config import settings
from app.scheduler import scheduler, setup_scheduler
from app.services import minio_service, nats_service


def _setup_json_logging() -> None:
    """Configure structured JSON logging for production observability."""
    from pythonjsonlogger.json import JsonFormatter

    formatter = JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


_setup_json_logging()

logger = logging.getLogger(__name__)


def _setup_telemetry(app: FastAPI) -> None:
    """Configure OpenTelemetry tracing (only when OTEL endpoint is set)."""
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": "markai-backend"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


async def _ensure_brand_sync_filter_columns() -> None:
    """Idempotently add bc_sync_vendor_nos / bc_sync_categories columns to brands.

    Used because this project doesn't currently ship Alembic migrations; new
    JSONB columns need to appear on existing databases without manual DDL.
    """
    from sqlalchemy import text
    from app.models.base import engine

    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE brands ADD COLUMN IF NOT EXISTS bc_sync_vendor_nos JSONB DEFAULT '[]'::jsonb NOT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE brands ADD COLUMN IF NOT EXISTS bc_sync_categories JSONB DEFAULT '[]'::jsonb NOT NULL"
        ))


async def _ensure_events_table() -> None:
    """Idempotently create the events table for the significant-days calendar.

    Same lifespan-migration pattern as brand sync filter columns — no Alembic
    in this repo, so schema additions ship via CREATE TABLE IF NOT EXISTS.
    """
    from sqlalchemy import text
    from app.models.base import engine

    ddl = """
    CREATE TABLE IF NOT EXISTS events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        start_date DATE NOT NULL,
        end_date DATE,
        is_annual BOOLEAN NOT NULL DEFAULT TRUE,
        category VARCHAR(64),
        source VARCHAR(32) NOT NULL DEFAULT 'manual',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS ix_events_brand_id ON events(brand_id);
    CREATE INDEX IF NOT EXISTS ix_events_start_date ON events(start_date);
    """
    async with engine.begin() as conn:
        # gen_random_uuid() needs pgcrypto; most Postgres installs have it,
        # but create the extension idempotently to be safe.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            await conn.execute(text(stmt))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("MARKAI backend starting up (env=%s)", settings.MARKAI_ENV)

    # Ensure schema additions exist (no-op when columns already present)
    try:
        await _ensure_brand_sync_filter_columns()
    except Exception as e:
        logger.error("Failed to ensure brand sync filter columns: %s", e)

    try:
        await _ensure_events_table()
    except Exception as e:
        logger.error("Failed to ensure events table: %s", e)

    # Setup APScheduler — must happen in async context so the scheduler
    # binds to uvicorn's event loop (not a detached one).
    import asyncio
    scheduler._eventloop = asyncio.get_running_loop()
    setup_scheduler()

    # Connect to NATS JetStream
    try:
        await nats_service.connect()
    except Exception as e:
        logger.error("Failed to connect to NATS: %s", e)

    # Ensure MinIO bucket exists
    try:
        await minio_service.ensure_bucket()
    except Exception as e:
        logger.error("Failed to ensure MinIO bucket: %s", e)

    yield

    # Shutdown
    scheduler.shutdown()
    await nats_service.disconnect()
    logger.info("MARKAI backend shut down")


limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

app = FastAPI(
    title="MARKAI API",
    description="Autonomous AI Marketing Operating System",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — never combine allow_origins=["*"] with allow_credentials=True
_frontend_url = settings.FRONTEND_URL or "http://localhost:3000"
_cors_origins = [_frontend_url]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# Security headers middleware
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Global exception handler — ensures CORS headers are present on 500 errors
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
import traceback as _tb  # noqa: E402


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log traceback but sanitize to avoid leaking secrets
    tb_text = _tb.format_exc()
    # Strip any lines containing known secret patterns
    sanitized_tb = "\n".join(
        line
        for line in tb_text.splitlines()
        if not any(
            s in line.lower()
            for s in (
                "secret",
                "password",
                "api_key",
                "token",
                "credential",
                "connection_string",
                "private_key",
                "signing_key",
                "access_key",
                "bearer",
                "client_secret",
            )
        )
    )
    logger.error(
        "Unhandled exception on %s %s: %s\n%s",
        request.method,
        request.url.path,
        type(exc).__name__,
        sanitized_tb,
    )
    # Use configured CORS origins instead of echoing the request's Origin header
    headers = {}
    _allowed_origin = settings.FRONTEND_URL or "http://localhost:3000"
    if _allowed_origin:
        headers["access-control-allow-origin"] = _allowed_origin
        headers["access-control-allow-credentials"] = "true"
    # Never expose internal exception details to the client
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )


# Health check endpoint (used by Docker healthcheck)
@app.get("/health")
async def health():
    return {"status": "ok"}


# OpenTelemetry (conditional)
if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
    _setup_telemetry(app)
else:
    logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set; OpenTelemetry disabled")

# Prometheus metrics
Instrumentator().instrument(app).expose(app, include_in_schema=False)

# Mount all v1 routers
app.include_router(api_router)
