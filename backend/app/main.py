import re as _re
import uuid as _uuid
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.admin.routes import router as admin_router
from app.auth.routes import router as auth_router
from app.bookings.routes import router as bookings_router
from app.config import settings
from app.database import async_session
from app.mechanics.routes import router as mechanics_router
from app.messages.routes import router as messages_router
from app.middleware import SecurityHeadersMiddleware
from app.notifications.routes import router as notifications_router
from app.payments.routes import router as payments_router
from app.referrals.routes import router as referrals_router
from app.reports.routes import router as reports_router
from app.reviews.routes import router as reviews_router
from app.utils.rate_limit import limiter

# FIX-1: Prometheus metrics for observability
from prometheus_fastapi_instrumentator import Instrumentator

# Configure structlog: JSON in production, console in development
processors = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]
if settings.is_production:
    processors.append(structlog.processors.JSONRenderer())
else:
    processors.append(structlog.dev.ConsoleRenderer())

structlog.configure(
    processors=processors,
    wrapper_class=structlog.make_filtering_bound_logger(0),
)

logger = structlog.get_logger()

# Sentry error tracking
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=0.1,
        environment=settings.APP_ENV,
        send_default_pii=False,
    )


async def _check_alembic_migration_version() -> None:
    """I-003: Log a WARNING if the database migration version does not match alembic head.

    This is a best-effort check that never crashes the application.
    """
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect as sa_inspect

        alembic_cfg = AlembicConfig("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        async with async_session() as session:
            conn = await session.connection()

            def _get_current_rev(connection):
                context = connection.dialect.has_table(connection, "alembic_version")
                if not context:
                    return None
                result = connection.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
                return row[0] if row else None

            current_rev = await conn.run_sync(_get_current_rev)

        if current_rev is None:
            logger.warning(
                "alembic_version_check",
                status="no_alembic_version_table",
                message="No alembic_version table found — database may not be initialized",
            )
        elif current_rev != head_rev:
            logger.warning(
                "alembic_version_mismatch",
                current=current_rev,
                head=head_rev,
                message="Database migration version does not match alembic head. Run 'alembic upgrade head'.",
            )
        else:
            logger.info("alembic_version_ok", version=current_rev)
    except Exception as exc:
        # I-003: Never crash the app — just log and continue
        logger.warning(
            "alembic_version_check_failed",
            error=str(exc),
            message="Could not verify database migration version",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.scheduler import scheduler, start_scheduler

    logger.info("emecano_startup", env=settings.APP_ENV)

    # I-003: Best-effort migration version check (never crashes)
    await _check_alembic_migration_version()

    # I-004: Warn if STRIPE_WEBHOOK_SECRET is not configured
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.warning(
            "stripe_webhook_secret_empty",
            message="STRIPE_WEBHOOK_SECRET is not set — webhook signature verification is disabled. "
                    "This is acceptable in development but MUST be configured in production.",
        )

    start_scheduler()
    yield
    scheduler.shutdown(wait=True)
    logger.info("emecano_shutdown")


app = FastAPI(
    title="eMecano API",
    description="Marketplace connecting mechanics with used car buyers in France",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return a safe 500 response in production."""
    logger.exception("unhandled_exception", path=request.url.path)
    if settings.APP_ENV != "development":
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    # In development, re-raise so the default handler shows the traceback
    raise exc


# Middleware is LIFO: the last middleware added runs first.
# CORS is added first so it runs last; SecurityHeaders is added after so it runs first.
if settings.is_production:
    # SEC-013: allow_credentials=True is safe here because allow_origins is set
    # to an explicit list from settings.cors_origins_list (never a wildcard "*").
    # Browsers enforce that credentialed requests are only allowed when the
    # Access-Control-Allow-Origin header matches a specific origin, which this
    # configuration guarantees.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    if not settings.cors_origins_list:
        logger.warning("cors_origins_empty_in_production", app_env=settings.APP_ENV)
else:
    # WARNING: Wildcard CORS is used ONLY in development/local mode.
    # In production the branch above restricts origins to settings.cors_origins_list.
    # Do NOT deploy with allow_origins=["*"] — it disables browser same-origin protections.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:8081", "http://localhost:19006"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# SEC-011: Security headers applied in ALL environments; HSTS only in production
app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)


_REQUEST_ID_RE = _re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request ID and measure duration for every request."""
    import time as _time

    # SEC-011: Validate X-Request-ID to prevent log injection
    client_id = request.headers.get("X-Request-ID")
    request_id = client_id if client_id and _REQUEST_ID_RE.match(client_id) else str(_uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = _time.monotonic()
    try:
        response = await call_next(request)
        duration_ms = (_time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration_ms:.1f}ms"
        # OBS-04: Log slow requests (>1s) as warnings
        if duration_ms > 1000:
            logger.warning(
                "slow_request",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 1),
                status_code=response.status_code,
            )
        return response
    finally:
        structlog.contextvars.clear_contextvars()


# FIX-1: Prometheus metrics — instrument the app and expose /metrics
# Custom instrumentation avoids the default metrics.default() function which
# crashes on non-numeric Content-Length headers (prometheus-fastapi-instrumentator bug).
def _safe_metrics(info) -> None:
    from prometheus_client import Counter, Histogram
    if not hasattr(_safe_metrics, "_total"):
        _safe_metrics._total = Counter(
            "emecano_http_requests_total", "Total HTTP requests",
            ["method", "status", "handler"],
        )
        _safe_metrics._latency = Histogram(
            "emecano_http_request_duration_seconds", "Request latency",
            ["method", "handler"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
        )
    _safe_metrics._total.labels(info.method, info.modified_status, info.modified_handler).inc()
    _safe_metrics._latency.labels(info.method, info.modified_handler).observe(info.modified_duration)


Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/health", "/metrics"],
).add(_safe_metrics).instrument(app)


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request):
    """Prometheus metrics endpoint (protected by API key)."""
    from prometheus_client import generate_latest
    from starlette.responses import Response as StarletteResponse

    # In production/staging, METRICS_API_KEY is required
    if settings.is_production and not settings.METRICS_API_KEY:
        raise HTTPException(status_code=503, detail="Metrics not available")

    if settings.METRICS_API_KEY:
        api_key = request.headers.get("x-metrics-key", "")
        if api_key != settings.METRICS_API_KEY:
            raise HTTPException(
                status_code=403,
                detail="Invalid metrics API key",
            )

    return StarletteResponse(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(mechanics_router, prefix="/mechanics", tags=["mechanics"])
app.include_router(bookings_router, prefix="/bookings", tags=["bookings"])
app.include_router(payments_router, prefix="/payments", tags=["payments"])
app.include_router(reviews_router, prefix="/reviews", tags=["reviews"])
app.include_router(referrals_router, prefix="/referrals", tags=["referrals"])
app.include_router(messages_router, tags=["messages"])
app.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
app.include_router(reports_router)
app.include_router(admin_router)


@app.get("/health")
@limiter.limit("60/minute")
async def health_check(request: Request):
    """Health check with database and Redis connectivity verification."""
    result: dict = {"status": "ok", "database": "connected", "redis": "connected"}

    # Database check
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected", "redis": "unknown"},
        )

    # Redis check (non-blocking: backend works without Redis via fallbacks)
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
    except Exception:
        result["redis"] = "unavailable"

    # AUDIT-FIX3: Verify scheduler is running
    try:
        from app.services.scheduler import scheduler
        result["scheduler"] = "running" if scheduler.running else "stopped"
    except Exception:
        result["scheduler"] = "unknown"

    if settings.is_production:
        db_ok = result.get("database") == "connected"
        redis_ok = result.get("redis") == "connected"
        sched_ok = result.get("scheduler") == "running"
        overall = "ok" if (db_ok and redis_ok and sched_ok) else "unhealthy"
        return {
            "status": overall,
            "database": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
            "scheduler": "ok" if sched_ok else "error",
        }
    return result
