from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.auth.routes import router as auth_router
from app.bookings.routes import router as bookings_router
from app.config import settings
from app.database import async_session
from app.mechanics.routes import router as mechanics_router
from app.middleware import SecurityHeadersMiddleware
from app.payments.routes import router as payments_router
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

if settings.is_production:
    app.add_middleware(SecurityHeadersMiddleware)

if settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(mechanics_router, prefix="/mechanics", tags=["mechanics"])
app.include_router(bookings_router, prefix="/bookings", tags=["bookings"])
app.include_router(payments_router, prefix="/payments", tags=["payments"])
app.include_router(reviews_router, prefix="/reviews", tags=["reviews"])


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
