from collections.abc import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = structlog.get_logger()

# SSL is required for production/staging PostgreSQL connections.
# SQLite (used in tests) does not support SSL connect_args.
_connect_args: dict = {}
if (
    settings.APP_ENV in ("production", "staging")
    and "sqlite" not in settings.DATABASE_URL
):
    _connect_args["ssl"] = "require"

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_DEBUG,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=3600,
    pool_timeout=30,
    connect_args=_connect_args,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("db_session_failed")
            raise
