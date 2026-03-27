import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.scheduler import scheduler, setup_scheduler
from app.services import minio_service, nats_service

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("MARKAI backend starting up (env=%s)", settings.MARKAI_ENV)

    # Setup APScheduler
    setup_scheduler()

    # Connect to NATS JetStream
    try:
        await nats_service.connect()
    except Exception as e:
        logger.error("Failed to connect to NATS: %s", e)

    # Ensure MinIO bucket exists
    try:
        minio_service.ensure_bucket()
    except Exception as e:
        logger.error("Failed to ensure MinIO bucket: %s", e)

    yield

    # Shutdown
    scheduler.shutdown()
    await nats_service.disconnect()
    logger.info("MARKAI backend shut down")


app = FastAPI(
    title="MARKAI API",
    description="Autonomous AI Marketing Operating System",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — never combine allow_origins=["*"] with allow_credentials=True
_frontend_url = settings.FRONTEND_URL or "http://localhost:3000"
_cors_origins = [_frontend_url]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler — ensures CORS headers are present on 500 errors
from fastapi import Request
from fastapi.responses import JSONResponse
import traceback as _tb

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log traceback but sanitize to avoid leaking secrets
    tb_text = _tb.format_exc()
    # Strip any lines containing known secret patterns
    sanitized_tb = "\n".join(
        line for line in tb_text.splitlines()
        if not any(s in line.lower() for s in ("secret", "password", "api_key", "token", "credential"))
    )
    logger.error("Unhandled exception on %s %s: %s\n%s", request.method, request.url.path, type(exc).__name__, sanitized_tb)
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

# Mount all v1 routers
app.include_router(api_router)
