# The response shapes for the saved-chart endpoints.

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.response import VisualizeResponse


class SavedChartSummary(BaseModel):
    # One line in the history list. No chart data, so the list stays small.

    id: str
    query: str
    title: str
    viz_type: str
    total_matching: int
    created_at: datetime
    refreshed_from_id: str | None = None


class SavedChartDetail(SavedChartSummary):
    # A saved chart with its full snapshot, ready to render

    response: VisualizeResponse


class RefreshResponse(BaseModel):
    # The result of re-running a saved chart against live data

    chart: SavedChartDetail = Field(description="The new, refreshed chart (saved as a new row).")
    previous_id: str
    previous_total_matching: int
    new_total_matching: int
