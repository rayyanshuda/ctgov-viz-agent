"""End-to-end plan execution against a mocked ClinicalTrials.gov.

The API is stubbed with the captured fixture page, so the full pipeline — retrieval,
normalization, aggregation, citation, response assembly — runs offline and
deterministically while still operating on real registry data.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.cache import ResponseCache
from app.ctgov.client import CTGovClient
from app.executor import PlanExecutor, enforce_user_filters
from app.models.plan import AnalysisPlan
from app.models.request import VisualizeRequest

FIXTURE = Path(__file__).parent / "fixtures" / "myeloma_page.json"
STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


def make_plan(analysis: dict, viz: dict, cohorts: list | None = None) -> AnalysisPlan:
    return AnalysisPlan.model_validate(
        {
            "interpretation": "A question about myeloma trials.",
            "assumptions": ["Interventional trials only."],
            "retrieval": {
                "cohorts": cohorts
                or [{"name": "Myeloma", "filters": {"conditions": ["multiple myeloma"]}}]
            },
            "analysis": analysis,
            "visualization": viz,
        }
    )


@pytest.fixture
def page() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def executor(settings, tmp_path):
    client = CTGovClient(settings, ResponseCache(tmp_path / "c", 60, enabled=False))
    return PlanExecutor(client, settings.max_studies)


@pytest.fixture
def mock_api(page):
    """Serve the fixture for any studies request, with no next page."""
    with respx.mock(assert_all_called=False) as mock:
        body = {**page, "nextPageToken": None}
        mock.get(url__startswith=STUDIES_URL).mock(
            return_value=httpx.Response(200, json=body)
        )
        yield mock


class TestGroupByExecution:
    async def test_produces_a_renderable_bar_chart(self, executor, mock_api):
        plan = make_plan(
            {"kind": "group_by", "dimension": "phase", "sort_by": "category"},
            {"type": "bar_chart", "title": "Myeloma Trials by Phase"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="phases?"))

        assert response.status == "ok"
        viz = response.visualization
        assert viz.type == "bar_chart"
        assert viz.encoding.x.field == "phase"
        assert viz.encoding.y.field == "trial_count"
        # The encoding must name keys that actually exist in the rows.
        assert all(viz.encoding.x.field in row for row in viz.data)
        assert all(viz.encoding.y.field in row for row in viz.data)

    async def test_every_datum_carries_citations(self, executor, mock_api):
        plan = make_plan(
            {"kind": "group_by", "dimension": "phase"},
            {"type": "bar_chart", "title": "Myeloma Trials by Phase"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="phases?"))

        for row in response.visualization.data:
            if row["trial_count"]:
                assert row["citations"], "a non-empty bucket must cite its sources"
                for citation in row["citations"]:
                    assert citation["nct_id"] in response.citation_index
                    assert citation["field"] == "protocolSection.designModule.phases"

    async def test_citation_excerpt_is_the_raw_value_behind_the_bucket_label(
        self, executor, mock_api
    ):
        """The excerpt must be the API's own value, and it must explain this bucket.

        The row shows a humanized label ("Active, not recruiting"); the citation quotes
        what the API actually returned ("ACTIVE_NOT_RECRUITING"). Checking they agree is
        what makes the citation evidence rather than decoration.
        """
        from app.ctgov.enums import humanize

        plan = make_plan(
            {"kind": "group_by", "dimension": "overall_status"},
            {"type": "bar_chart", "title": "Recruitment Status"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="status?"))

        checked = 0
        for row in response.visualization.data:
            for citation in row["citations"]:
                assert humanize(citation["excerpt"]) == row["overall_status"]
                checked += 1
        assert checked > 0, "expected at least one citation to verify"

    async def test_meta_states_counting_semantics_and_coverage(self, executor, mock_api):
        plan = make_plan(
            {"kind": "group_by", "dimension": "country"},
            {"type": "geo_map", "title": "Countries"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="countries?"))

        assert "counted once per value" in response.meta.counting_semantics
        assert response.meta.coverage.analyzed == 120
        assert response.meta.coverage.total_matching == 4028
        assert response.meta.coverage.truncated is True
        assert any("Analyzed 120" in w for w in response.meta.warnings)

    async def test_geo_map_rows_carry_iso3_codes(self, executor, mock_api):
        plan = make_plan(
            {"kind": "group_by", "dimension": "country"},
            {"type": "geo_map", "title": "Countries"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="countries?"))
        assert response.visualization.encoding.location.field == "country_iso3"
        codes = [r.get("country_iso3") for r in response.visualization.data]
        assert "USA" in codes

    async def test_ctgov_requests_are_echoed_for_reproducibility(self, executor, mock_api):
        plan = make_plan(
            {"kind": "group_by", "dimension": "phase"},
            {"type": "bar_chart", "title": "Phases"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="phases?"))
        assert response.meta.ctgov_requests
        assert response.meta.ctgov_requests[0]["query.cond"] == "multiple myeloma"


class TestNetworkExecution:
    async def test_produces_nodes_and_edges_not_rows(self, executor, mock_api):
        plan = make_plan(
            {
                "kind": "network",
                "source_dimension": "lead_sponsor",
                "target_dimension": "intervention_mesh",
                "min_edge_weight": 1,
            },
            {"type": "network_graph", "title": "Sponsors and Drugs"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="network?"))

        viz = response.visualization
        assert viz.type == "network_graph"
        assert viz.nodes and viz.edges
        assert viz.data == []
        assert viz.encoding.node is not None and viz.encoding.edge is not None
        ids = {n["id"] for n in viz.nodes}
        assert all(e["source"] in ids and e["target"] in ids for e in viz.edges)

    async def test_edges_cite_the_trials_linking_them(self, executor, mock_api):
        plan = make_plan(
            {
                "kind": "network",
                "source_dimension": "lead_sponsor",
                "target_dimension": "intervention_mesh",
                "min_edge_weight": 1,
            },
            {"type": "network_graph", "title": "Sponsors and Drugs"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="network?"))
        assert all(e["citations"] for e in response.visualization.edges)


class TestOtherAnalyses:
    async def test_kpi_returns_a_headline_figure(self, executor, mock_api):
        plan = make_plan(
            {"kind": "kpi", "measure": "trial_count", "breakdown_dimension": "phase"},
            {"type": "kpi", "title": "Myeloma Trial Count"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="how many?"))
        assert response.visualization.type == "kpi"
        assert response.visualization.data[0]["trial_count"] == 120
        assert len(response.visualization.data) > 1, "breakdown rows should follow"

    async def test_histogram_bins_and_reports_exclusions(self, executor, mock_api):
        plan = make_plan(
            {"kind": "histogram", "metric": "enrollment", "bin_count": 10},
            {"type": "histogram", "title": "Enrollment Distribution"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="sizes?"))
        assert len(response.visualization.data) == 10
        assert sum(r["trial_count"] for r in response.visualization.data) <= 120
        assert any("did not report" in w for w in response.meta.warnings)

    async def test_scatter_emits_one_point_per_trial(self, executor, mock_api):
        plan = make_plan(
            {"kind": "scatter", "x_metric": "start_year", "y_metric": "enrollment"},
            {"type": "scatter_plot", "title": "Enrollment Over Time"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="scatter?"))
        rows = response.visualization.data
        assert all("nct_id" in r and "start_year" in r and "enrollment" in r for r in rows)
        assert len({r["nct_id"] for r in rows}) == len(rows)


class TestComparisons:
    async def test_two_cohorts_become_a_series(self, executor, mock_api):
        plan = make_plan(
            {"kind": "group_by", "dimension": "phase", "series_dimension": "cohort"},
            {"type": "grouped_bar_chart", "title": "A vs B"},
            cohorts=[
                {"name": "Bortezomib", "filters": {"interventions": ["bortezomib"]}},
                {"name": "Lenalidomide", "filters": {"interventions": ["lenalidomide"]}},
            ],
        )
        response = await executor.execute(plan, VisualizeRequest(query="compare"))

        assert response.visualization.encoding.series.field == "cohort"
        assert {r["cohort"] for r in response.visualization.data} == {
            "Bortezomib",
            "Lenalidomide",
        }
        assert len(response.meta.coverage.per_cohort) == 2


class TestNoData:
    async def test_empty_result_is_reported_not_fabricated(self, executor, page):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=STUDIES_URL).mock(
                return_value=httpx.Response(200, json={"studies": [], "totalCount": 0})
            )
            plan = make_plan(
                {"kind": "group_by", "dimension": "phase"},
                {"type": "bar_chart", "title": "Nothing"},
            )
            response = await executor.execute(plan, VisualizeRequest(query="nothing"))

        assert response.status == "no_data"
        assert response.visualization is None
        assert any("No trials matched" in w for w in response.meta.warnings)
        assert response.meta.ctgov_requests, "the attempted query is still reported"


class TestUserFilterPrecedence:
    def test_request_filters_override_the_planners_choice(self):
        plan = make_plan(
            {"kind": "group_by", "dimension": "phase"},
            {"type": "bar_chart", "title": "Title"},
        )
        enforced, warnings = enforce_user_filters(
            plan, VisualizeRequest(query="a question", condition="melanoma", start_year=2018)
        )
        assert plan.retrieval.cohorts[0].filters.conditions == ["melanoma"]
        assert plan.retrieval.cohorts[0].filters.start_year_min == 2018
        assert enforced["condition"] == ["melanoma"]
        assert warnings == []

    def test_a_field_distinguishing_cohorts_is_not_overridden(self):
        plan = make_plan(
            {"kind": "group_by", "dimension": "phase", "series_dimension": "cohort"},
            {"type": "grouped_bar_chart", "title": "Title"},
            cohorts=[
                {"name": "A", "filters": {"interventions": ["bortezomib"]}},
                {"name": "B", "filters": {"interventions": ["lenalidomide"]}},
            ],
        )
        _, warnings = enforce_user_filters(
            plan, VisualizeRequest(query="a question", drug_name="pembrolizumab")
        )
        # Overriding here would collapse "A vs B" into "A vs A".
        assert plan.retrieval.cohorts[0].filters.interventions == ["bortezomib"]
        assert plan.retrieval.cohorts[1].filters.interventions == ["lenalidomide"]
        assert any("collapse the comparison" in w for w in warnings)

    def test_shared_fields_still_apply_across_cohorts(self):
        plan = make_plan(
            {"kind": "group_by", "dimension": "phase", "series_dimension": "cohort"},
            {"type": "grouped_bar_chart", "title": "Title"},
            cohorts=[
                {"name": "A", "filters": {"interventions": ["bortezomib"]}},
                {"name": "B", "filters": {"interventions": ["lenalidomide"]}},
            ],
        )
        enforce_user_filters(plan, VisualizeRequest(query="a question", trial_phase=["PHASE3"]))
        assert all(c.filters.phases == ["PHASE3"] for c in plan.retrieval.cohorts)


class TestHistogramBinning:
    """Bins must describe values that can actually occur.

    Log-scaled bins over an integer metric previously produced edges like 1.0, 1.29,
    1.67 — rendering as the meaningless labels "1–1" and "2–2", with empty bins between
    them, because no trial can enrol 1.29 participants.
    """

    async def test_integer_metric_bins_are_whole_numbers(self, executor, mock_api):
        plan = make_plan(
            {"kind": "histogram", "metric": "enrollment", "bin_count": 30, "log_scale": True},
            {"type": "histogram", "title": "Enrollment Distribution"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="sizes?"))
        rows = response.visualization.data

        for row in rows:
            assert row["bin_start"] == int(row["bin_start"])
            assert row["bin_end"] == int(row["bin_end"])

    async def test_bin_labels_are_unique_and_non_degenerate(self, executor, mock_api):
        plan = make_plan(
            {"kind": "histogram", "metric": "enrollment", "bin_count": 30, "log_scale": True},
            {"type": "histogram", "title": "Enrollment Distribution"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="sizes?"))
        labels = [row["bin"] for row in response.visualization.data]

        assert len(labels) == len(set(labels)), f"duplicate bin labels: {labels}"
        for label in labels:
            if "–" in label:
                low, high = label.replace(",", "").split("–")
                assert int(low) < int(high), f"degenerate bin {label!r}"

    async def test_bins_do_not_overlap(self, executor, mock_api):
        plan = make_plan(
            {"kind": "histogram", "metric": "enrollment", "bin_count": 12},
            {"type": "histogram", "title": "Enrollment Distribution"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="sizes?"))
        rows = response.visualization.data
        for earlier, later in zip(rows, rows[1:], strict=False):
            assert earlier["bin_end"] <= later["bin_start"]

    async def test_every_trial_with_the_metric_lands_in_exactly_one_bin(
        self, executor, mock_api, records
    ):
        plan = make_plan(
            {"kind": "histogram", "metric": "enrollment", "bin_count": 12},
            {"type": "histogram", "title": "Enrollment Distribution"},
        )
        response = await executor.execute(plan, VisualizeRequest(query="sizes?"))
        binned = sum(row["trial_count"] for row in response.visualization.data)
        reported = sum(1 for r in records if r.enrollment is not None)
        assert binned == reported
