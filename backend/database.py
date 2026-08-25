from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

logger = logging.getLogger(__name__)


def _get_engine():
    url = settings.database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    connect_args = {}
    if "sqlite" in url:
        connect_args = {"check_same_thread": False}

    return create_async_engine(url, echo=settings.debug, connect_args=connect_args)


engine = _get_engine()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    db_type = "PostgreSQL" if "postgres" in settings.database_url else "SQLite"
    logger.info("Initializing %s database", db_type)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
