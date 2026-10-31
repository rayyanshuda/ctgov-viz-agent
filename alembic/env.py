# Alembic's entry point. Alembic is the tool that creates and changes our database tables.
# Run it with:  alembic upgrade head

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db.engine import async_url
from app.db.models import Base

# The table definitions Alembic compares against when it generates a migration
target_metadata = Base.metadata


def run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    url = get_settings().database_url
    if not url:
        raise SystemExit("Set CTGOV_VIZ_DATABASE_URL before running migrations.")
    engine = create_async_engine(async_url(url))
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


asyncio.run(main())
