import uuid as _uuid
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI, Request
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
    sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1, environment=settings.APP_ENV)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.scheduler import scheduler, start_scheduler

    logger.info("emecano_startup", env=settings.APP_ENV)
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
    if settings.is_production:
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
else:
    # WARNING: Wildcard CORS is used ONLY in development/local mode.
    # In production the branch above restricts origins to settings.cors_origins_list.
    # Do NOT deploy with allow_origins=["*"] — it disables browser same-origin protections.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

if settings.is_production:
    app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request ID to every request for tracing."""
    request_id = request.headers.get("X-Request-ID") or str(_uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        structlog.contextvars.clear_contextvars()


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
async def health_check():
    """Health check with database connectivity verification."""
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected"},
        )
