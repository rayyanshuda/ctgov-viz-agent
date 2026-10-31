# The few database operations the app needs. Each function does one thing.

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SavedChart
from app.models.plan import AnalysisPlan
from app.models.request import VisualizeRequest
from app.models.response import VisualizeResponse


async def save_chart(
    session: AsyncSession,
    request: VisualizeRequest,
    plan: AnalysisPlan,
    response: VisualizeResponse,
    refreshed_from_id: str | None = None,
) -> SavedChart:
    # mode="json" turns dates and enums into plain JSON values the database can store
    row = SavedChart(
        id=secrets.token_urlsafe(8),
        query=request.query,
        # [:300] keeps an unusually long title within the column size
        title=(response.visualization.title if response.visualization else request.query)[:300],
        viz_type=response.visualization.type if response.visualization else "none",
        total_matching=response.meta.coverage.total_matching,
        request=request.model_dump(mode="json"),
        plan=plan.model_dump(mode="json"),
        response=response.model_dump(mode="json", exclude_none=True),
        refreshed_from_id=refreshed_from_id,
    )
    session.add(row)
    await session.commit()
    return row


async def get_chart(session: AsyncSession, chart_id: str) -> SavedChart | None:
    return await session.get(SavedChart, chart_id)


async def list_charts(session: AsyncSession, limit: int, offset: int) -> list[SavedChart]:
    # Newest first
    stmt = select(SavedChart).order_by(SavedChart.created_at.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def delete_chart(session: AsyncSession, chart_id: str) -> bool:
    row = await session.get(SavedChart, chart_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
