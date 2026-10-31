"""Saved charts: saving on /visualize, opening, listing, refreshing and deleting.

These run on a throwaway SQLite file, so they need no Postgres server. The planner and
ClinicalTrials.gov are stubbed the same way as in test_api.py.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.agent.planner import PlanningResult
from app.db.engine import make_engine
from app.db.models import Base
from app.main import create_app
from tests.test_api import FIXTURE, PLAN, STUDIES_URL

QUESTION = {"query": "How are myeloma trials distributed across phases?"}


def _create_tables(url: str) -> None:
    async def run() -> None:
        engine = make_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(run())


def _make_client(monkeypatch, tmp_path, database_url: str | None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CTGOV_VIZ_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("CTGOV_VIZ_CACHE_ENABLED", "false")
    monkeypatch.setenv("CTGOV_VIZ_RATE_LIMIT_ENABLED", "false")
    if database_url:
        monkeypatch.setenv("CTGOV_VIZ_DATABASE_URL", database_url)
        _create_tables(database_url)
    else:
        monkeypatch.delenv("CTGOV_VIZ_DATABASE_URL", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()

    async def fake_plan(self, request):
        return PlanningResult(plan=PLAN.model_copy(deep=True))

    monkeypatch.setattr("app.agent.planner.LLMPlanner.plan", fake_plan)
    return TestClient(create_app()), get_settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    test_client, get_settings = _make_client(
        monkeypatch, tmp_path, f"sqlite+aiosqlite:///{tmp_path / 'charts.db'}"
    )
    with test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def client_without_db(monkeypatch, tmp_path):
    test_client, get_settings = _make_client(monkeypatch, tmp_path, None)
    with test_client:
        yield test_client
    get_settings.cache_clear()


def _page(**overrides) -> dict:
    return {**json.loads(FIXTURE.read_text()), "nextPageToken": None, **overrides}


@pytest.fixture
def mock_ctgov():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url__startswith=STUDIES_URL)
        route.mock(return_value=httpx.Response(200, json=_page()))
        mock.route = route  # tests can swap what the "API" returns
        yield mock


class TestSaving:
    def test_visualize_saves_the_chart_and_returns_its_id(self, client, mock_ctgov):
        body = client.post("/api/v1/visualize", json=QUESTION).json()
        assert body["chart_id"]

        saved = client.get(f"/api/v1/charts/{body['chart_id']}").json()
        assert saved["id"] == body["chart_id"]
        assert saved["response"]["visualization"] == body["visualization"]

    def test_a_chart_with_no_data_is_not_saved(self, client, mock_ctgov):
        mock_ctgov.route.mock(
            return_value=httpx.Response(200, json=_page(totalCount=0, studies=[]))
        )
        body = client.post("/api/v1/visualize", json=QUESTION).json()
        assert body["status"] == "no_data"
        assert "chart_id" not in body
        assert client.get("/api/v1/charts").json() == []

    def test_without_a_database_everything_else_still_works(self, client_without_db, mock_ctgov):
        body = client_without_db.post("/api/v1/visualize", json=QUESTION).json()
        assert body["status"] == "ok"
        assert "chart_id" not in body

        blocked = client_without_db.get("/api/v1/charts")
        assert blocked.status_code == 503
        assert blocked.json()["error"] == "configuration_error"


class TestReading:
    def test_list_is_newest_first_and_carries_no_chart_data(self, client, mock_ctgov):
        first = client.post("/api/v1/visualize", json=QUESTION).json()["chart_id"]
        second = client.post("/api/v1/visualize", json=QUESTION).json()["chart_id"]

        rows = client.get("/api/v1/charts").json()
        assert [r["id"] for r in rows] == [second, first]
        assert "response" not in rows[0]
        assert rows[0]["viz_type"] == "bar_chart"

    def test_list_respects_limit_and_offset(self, client, mock_ctgov):
        for _ in range(3):
            client.post("/api/v1/visualize", json=QUESTION)
        assert len(client.get("/api/v1/charts?limit=2").json()) == 2
        assert len(client.get("/api/v1/charts?limit=2&offset=2").json()) == 1

    def test_unknown_id_is_a_404(self, client):
        response = client.get("/api/v1/charts/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"] == "chart_not_found"


class TestRefresh:
    def test_refresh_saves_a_new_chart_linked_to_the_old_one(self, client, mock_ctgov):
        original_id = client.post("/api/v1/visualize", json=QUESTION).json()["chart_id"]

        # ClinicalTrials.gov now reports more matching trials than it did before
        mock_ctgov.route.mock(return_value=httpx.Response(200, json=_page(totalCount=9999)))
        refreshed = client.post(f"/api/v1/charts/{original_id}/refresh").json()

        assert refreshed["previous_id"] == original_id
        assert refreshed["chart"]["id"] != original_id
        assert refreshed["chart"]["refreshed_from_id"] == original_id
        assert refreshed["new_total_matching"] == 9999
        assert refreshed["new_total_matching"] > refreshed["previous_total_matching"]

        # The old snapshot is untouched
        old = client.get(f"/api/v1/charts/{original_id}").json()
        assert old["total_matching"] == refreshed["previous_total_matching"]
        assert len(client.get("/api/v1/charts").json()) == 2

    def test_refresh_works_even_when_the_response_left_out_the_plan(self, client, mock_ctgov):
        # The plan is stored in its own column because include_plan=false removes it from
        # the response. Refresh must not depend on the response having it.
        payload = {**QUESTION, "options": {"include_plan": False}}
        body = client.post("/api/v1/visualize", json=payload).json()
        assert "plan" not in body

        refreshed = client.post(f"/api/v1/charts/{body['chart_id']}/refresh")
        assert refreshed.status_code == 200

    def test_refresh_of_an_unknown_chart_is_a_404(self, client):
        assert client.post("/api/v1/charts/nope/refresh").status_code == 404


class TestDelete:
    def test_delete_removes_the_chart(self, client, mock_ctgov):
        chart_id = client.post("/api/v1/visualize", json=QUESTION).json()["chart_id"]
        assert client.delete(f"/api/v1/charts/{chart_id}").status_code == 204
        assert client.get(f"/api/v1/charts/{chart_id}").status_code == 404

    def test_deleting_an_unknown_chart_is_a_404(self, client):
        assert client.delete("/api/v1/charts/nope").status_code == 404
