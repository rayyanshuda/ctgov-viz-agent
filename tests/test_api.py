"""HTTP surface: routing, error mapping, and the self-describing contract."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.agent.planner import PlanningResult
from app.errors import UpstreamError
from app.main import create_app
from app.models.plan import AnalysisPlan

FIXTURE = Path(__file__).parent / "fixtures" / "myeloma_page.json"
STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"

PLAN = AnalysisPlan.model_validate(
    {
        "interpretation": "Phase distribution of myeloma trials.",
        "assumptions": ["Interventional trials only."],
        "retrieval": {"cohorts": [{"name": "Myeloma", "filters": {"conditions": ["myeloma"]}}]},
        "analysis": {"kind": "group_by", "dimension": "phase", "sort_by": "category"},
        "visualization": {"type": "bar_chart", "title": "Myeloma Trials by Phase"},
    }
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A test client whose planner is stubbed, so no API key or model call is needed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CTGOV_VIZ_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("CTGOV_VIZ_CACHE_ENABLED", "false")

    from app.config import get_settings

    get_settings.cache_clear()

    async def fake_plan(self, request):
        return PlanningResult(plan=PLAN.model_copy(deep=True))

    monkeypatch.setattr("app.agent.planner.LLMPlanner.plan", fake_plan)

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()


@pytest.fixture
def mock_ctgov():
    page = json.loads(FIXTURE.read_text())
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith=STUDIES_URL).mock(
            return_value=httpx.Response(200, json={**page, "nextPageToken": None})
        )
        yield mock


class TestHealth:
    def test_reports_configuration_state(self, client):
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["planner_configured"] is True


class TestCapabilities:
    def test_publishes_the_registries(self, client):
        body = client.get("/api/v1/capabilities").json()
        dimension_ids = {d["id"] for d in body["dimensions"]}
        assert {"phase", "country", "intervention_mesh", "cohort"} <= dimension_ids
        assert {"trial_count", "median_enrollment"} <= {m["id"] for m in body["measures"]}
        assert len(body["visualization_types"]) == 10

    def test_network_graph_is_flagged_as_using_a_different_payload(self, client):
        body = client.get("/api/v1/capabilities").json()
        network = next(v for v in body["visualization_types"] if v["type"] == "network_graph")
        assert network["payload"] == "nodes+edges"

    def test_filter_vocabularies_are_published(self, client):
        filters = client.get("/api/v1/capabilities").json()["filters"]
        assert "PHASE3" in filters["phases"]
        assert "RECRUITING" in filters["statuses"]


class TestVisualize:
    def test_returns_a_complete_specification(self, client, mock_ctgov):
        response = client.post("/api/v1/visualize", json={"query": "phases for myeloma?"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["question"] == "phases for myeloma?"
        assert body["visualization"]["type"] == "bar_chart"
        assert body["meta"]["counting_semantics"]
        assert body["plan"]["analysis"]["dimension"] == "phase"

    def test_plan_can_be_omitted(self, client, mock_ctgov):
        response = client.post(
            "/api/v1/visualize",
            json={"query": "phases for myeloma?", "options": {"include_plan": False}},
        )
        assert response.json().get("plan") is None

    def test_citations_can_be_disabled(self, client, mock_ctgov):
        response = client.post(
            "/api/v1/visualize",
            json={"query": "phases?", "options": {"include_citations": False}},
        )
        body = response.json()
        assert all("citations" not in row for row in body["visualization"]["data"])
        assert body["citation_index"] == {}

    def test_citation_count_is_respected(self, client, mock_ctgov):
        response = client.post(
            "/api/v1/visualize",
            json={"query": "phases?", "options": {"citations_per_datum": 1}},
        )
        rows = response.json()["visualization"]["data"]
        assert all(len(r.get("citations", [])) <= 1 for r in rows)


class TestPlanEndpoint:
    def test_returns_the_plan_without_fetching_data(self, client):
        response = client.post("/api/v1/plan", json={"query": "phases for myeloma?"})
        assert response.status_code == 200
        assert response.json()["analysis"]["dimension"] == "phase"


class TestRequestValidation:
    def test_query_is_required(self, client):
        assert client.post("/api/v1/visualize", json={}).status_code == 422

    def test_too_short_query_is_rejected(self, client):
        assert client.post("/api/v1/visualize", json={"query": "x"}).status_code == 422

    def test_unknown_field_is_rejected(self, client):
        response = client.post("/api/v1/visualize", json={"query": "hello", "bogus": 1})
        assert response.status_code == 422

    def test_invalid_enum_value_is_rejected(self, client):
        response = client.post(
            "/api/v1/visualize", json={"query": "hello there", "trial_phase": ["PHASE_III"]}
        )
        assert response.status_code == 422

    def test_a_bare_string_is_accepted_where_a_list_is_expected(self, client, mock_ctgov):
        response = client.post(
            "/api/v1/visualize", json={"query": "phases?", "drug_name": "aspirin"}
        )
        assert response.status_code == 200
        assert response.json()["meta"]["filters_applied"]["user"]["drug_name"] == ["aspirin"]

    def test_reversed_year_range_is_rejected(self, client):
        response = client.post(
            "/api/v1/visualize",
            json={"query": "trends over time", "start_year": 2020, "end_year": 2010},
        )
        assert response.status_code == 422


class TestErrorMapping:
    def test_upstream_failure_becomes_502_with_a_remedy(self, client, monkeypatch):
        async def boom(self, *args, **kwargs):
            raise UpstreamError("ClinicalTrials.gov is unreachable.")

        monkeypatch.setattr("app.ctgov.client.CTGovClient.fetch", boom)
        response = client.post("/api/v1/visualize", json={"query": "phases?"})
        assert response.status_code == 502
        body = response.json()
        assert body["error"] == "upstream_error"
        assert body["remedy"]

    def test_missing_api_key_becomes_503(self, monkeypatch, tmp_path):
        # Set it empty rather than deleting: an env var takes precedence over the .env
        # file, so deleting alone would let a developer's real key leak into the test.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("CTGOV_VIZ_CACHE_ENABLED", "false")
        from app.config import get_settings

        get_settings.cache_clear()
        with TestClient(create_app()) as bare:
            response = bare.post("/api/v1/visualize", json={"query": "phases?"})
        get_settings.cache_clear()

        assert response.status_code == 503
        assert response.json()["error"] == "configuration_error"
        assert "ANTHROPIC_API_KEY" in response.json()["message"]


class TestOpenAPI:
    def test_schema_documents_every_endpoint(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert set(paths) == {
            "/api/v1/visualize",
            "/api/v1/plan",
            "/api/v1/capabilities",
            "/api/v1/health",
        }
