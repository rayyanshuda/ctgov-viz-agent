# The database table for saved charts.

# One row = one chart the user generated. We keep three things in each row:
#   - the request and plan that produced it (so it can be re-run later)
#   - the full response (the snapshot, so the chart can be shown exactly as it was)
# Rows are never edited. Refreshing a chart adds a new row that points back at the old
# one through refreshed_from_id, so the history of a chart is always preserved.

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SavedChart(Base):
    __tablename__ = "saved_charts"

    # Short random id used in share links, e.g. /c/Xk2m9QpL4Aw
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    query: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(300))
    viz_type: Mapped[str] = mapped_column(String(50))
    total_matching: Mapped[int] = mapped_column(Integer)

    # JSON columns: the saved request, the plan the model made, and the finished response
    request: Mapped[dict] = mapped_column(JSON)
    plan: Mapped[dict] = mapped_column(JSON)
    response: Mapped[dict] = mapped_column(JSON)

    # Set when this row was made by refreshing an older chart. If the old chart is deleted,
    # this just becomes empty instead of blocking the delete.
    refreshed_from_id: Mapped[str | None] = mapped_column(
        ForeignKey("saved_charts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
