# Endpoints for saved charts: list, open, refresh, delete.

# The chart itself is created by POST /visualize. These endpoints only read, re-run or
# remove charts that were already saved.

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ratelimit import enforce_rate_limit
from app.db import repo
from app.db.models import SavedChart
from app.errors import ChartNotFoundError, ConfigurationError
from app.executor import PlanExecutor
from app.models.chart import RefreshResponse, SavedChartDetail, SavedChartSummary
from app.models.plan import AnalysisPlan
from app.models.request import VisualizeRequest
from app.models.response import VisualizeResponse

router = APIRouter(prefix="/charts", tags=["saved charts"])


async def get_session(request: Request):
    # Opens one database session for the request and closes it afterwards.
    factory = request.app.state.db
    if factory is None:
        raise ConfigurationError(
            "Saved charts are switched off because no database is configured.",
            remedy="Set CTGOV_VIZ_DATABASE_URL and restart the service.",
        )
    async with factory() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


def _summary_fields(row: SavedChart) -> dict:
    return {
        "id": row.id,
        "query": row.query,
        "title": row.title,
        "viz_type": row.viz_type,
        "total_matching": row.total_matching,
        "created_at": row.created_at,
        "refreshed_from_id": row.refreshed_from_id,
    }


def _detail(row: SavedChart) -> SavedChartDetail:
    # The stored response doesn't know its own id, so we put it back in
    response = VisualizeResponse.model_validate({**row.response, "chart_id": row.id})
    return SavedChartDetail(**_summary_fields(row), response=response)


async def _load(session: AsyncSession, chart_id: str) -> SavedChart:
    row = await repo.get_chart(session, chart_id)
    if row is None:
        raise ChartNotFoundError(f"No saved chart with id '{chart_id}'.")
    return row


@router.get("", response_model=list[SavedChartSummary], summary="List saved charts, newest first")
async def list_saved(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SavedChartSummary]:
    rows = await repo.list_charts(session, limit, offset)
    return [SavedChartSummary(**_summary_fields(r)) for r in rows]


@router.get(
    "/{chart_id}",
    response_model=SavedChartDetail,
    response_model_exclude_none=True,
    summary="Open a saved chart exactly as it was generated",
)
async def get_saved(chart_id: str, session: Session) -> SavedChartDetail:
    return _detail(await _load(session, chart_id))


@router.post(
    "/{chart_id}/refresh",
    response_model=RefreshResponse,
    response_model_exclude_none=True,
    summary="Re-run a saved chart against live ClinicalTrials.gov data",
    description=(
        "Re-uses the saved plan, so no language model is called. The result is saved as a "
        "new chart linked to the old one; the old chart is left untouched."
    ),
    dependencies=[Depends(enforce_rate_limit)],
)
async def refresh(chart_id: str, request: Request, session: Session) -> RefreshResponse:
    old = await _load(session, chart_id)

    plan = AnalysisPlan.model_validate(old.plan)
    original_request = VisualizeRequest.model_validate(old.request)

    executor = PlanExecutor(request.app.state.ctgov_client, request.app.state.settings.max_studies)
    response = await executor.execute(plan, original_request)

    # Even if the data now matches no trials, we save that result: it is true information,
    # and the original chart is still there because we never overwrite old rows.
    new = await repo.save_chart(session, original_request, plan, response, refreshed_from_id=old.id)
    return RefreshResponse(
        chart=_detail(new),
        previous_id=old.id,
        previous_total_matching=old.total_matching,
        new_total_matching=new.total_matching,
    )


@router.delete("/{chart_id}", status_code=204, summary="Delete a saved chart")
async def delete_saved(chart_id: str, session: Session) -> Response:
    if not await repo.delete_chart(session, chart_id):
        raise ChartNotFoundError(f"No saved chart with id '{chart_id}'.")
    return Response(status_code=204)
