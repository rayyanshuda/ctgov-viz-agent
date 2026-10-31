# Creates the database connection.

# Everything else in the app talks to the database through a "session factory": a
# function that hands out short-lived sessions (one per request).

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def async_url(url: str) -> str:
    # Hosts hand out URLs like postgres://... or postgresql://..., but SQLAlchemy needs to be
    # told to use the async driver (asyncpg), so we rewrite the start of the URL.
    for old in ("postgres://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+asyncpg://" + url[len(old):]
    return url


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(async_url(database_url), pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False lets us still read a row's fields after saving it
    return async_sessionmaker(engine, expire_on_commit=False)
