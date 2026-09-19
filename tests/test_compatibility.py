"""The visualization compatibility matrix and its deterministic fallbacks."""

from __future__ import annotations

import pytest

from app.models.plan import AnalysisPlan
from app.viz.compatibility import default_visualization, resolve_visualization

BASE = {
    "interpretation": "A question about trials.",
    "retrieval": {"cohorts": [{"name": "A", "filters": {"conditions": ["melanoma"]}}]},
}


def plan(analysis: dict, viz_type: str) -> AnalysisPlan:
    return AnalysisPlan.model_validate(
        {**BASE, "analysis": analysis, "visualization": {"type": viz_type, "title": "A Title"}}
    )


GROUP_BY_PHASE = {"kind": "group_by", "dimension": "phase"}
GROUP_BY_YEAR = {"kind": "group_by", "dimension": "start_year"}
GROUP_BY_COUNTRY = {"kind": "group_by", "dimension": "country"}
NETWORK = {
    "kind": "network",
    "source_dimension": "lead_sponsor",
    "target_dimension": "intervention_mesh",
}


class TestValidCombinations:
    @pytest.mark.parametrize(
        ("analysis", "viz"),
        [
            (GROUP_BY_PHASE, "bar_chart"),
            (GROUP_BY_YEAR, "time_series"),
            (GROUP_BY_COUNTRY, "geo_map"),
            (GROUP_BY_PHASE, "table"),
            (NETWORK, "network_graph"),
            ({"kind": "histogram", "metric": "enrollment"}, "histogram"),
            ({"kind": "kpi"}, "kpi"),
            (
                {"kind": "scatter", "x_metric": "enrollment", "y_metric": "start_year"},
                "scatter_plot",
            ),
        ],
    )
    def test_are_left_alone(self, analysis, viz):
        resolved, warnings = resolve_visualization(plan(analysis, viz))
        assert resolved == viz and warnings == []


class TestFallbacks:
    def test_time_series_needs_a_temporal_dimension(self):
        resolved, warnings = resolve_visualization(plan(GROUP_BY_PHASE, "time_series"))
        assert resolved == "bar_chart"
        assert "temporal" in warnings[0]

    def test_map_needs_a_geographic_dimension(self):
        resolved, warnings = resolve_visualization(plan(GROUP_BY_PHASE, "geo_map"))
        assert resolved == "bar_chart"
        assert "geographic" in warnings[0]

    def test_grouped_bar_needs_a_series(self):
        resolved, warnings = resolve_visualization(plan(GROUP_BY_PHASE, "grouped_bar_chart"))
        assert resolved == "bar_chart"
        assert "series_dimension" in warnings[0]

    def test_chart_type_from_the_wrong_analysis_is_replaced(self):
        resolved, warnings = resolve_visualization(plan(NETWORK, "bar_chart"))
        assert resolved == "network_graph"
        assert warnings

    def test_every_fallback_is_reported_to_the_caller(self):
        _, warnings = resolve_visualization(plan(GROUP_BY_PHASE, "geo_map"))
        assert len(warnings) == 1 and "replaced" in warnings[0]


class TestPromotion:
    def test_bar_chart_with_a_series_becomes_grouped(self):
        analysis = {**GROUP_BY_PHASE, "series_dimension": "cohort"}
        resolved, warnings = resolve_visualization(plan(analysis, "bar_chart"))
        assert resolved == "grouped_bar_chart"
        assert "Promoted" in warnings[0]


class TestDefaults:
    @pytest.mark.parametrize(
        ("analysis", "expected"),
        [
            (GROUP_BY_YEAR, "time_series"),
            (GROUP_BY_COUNTRY, "geo_map"),
            (GROUP_BY_PHASE, "bar_chart"),
            ({**GROUP_BY_PHASE, "series_dimension": "cohort"}, "grouped_bar_chart"),
            (NETWORK, "network_graph"),
            ({"kind": "kpi"}, "kpi"),
        ],
    )
    def test_default_matches_the_analysis_shape(self, analysis, expected):
        assert default_visualization(plan(analysis, "table")) == expected
