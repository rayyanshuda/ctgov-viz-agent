# Which chart types are valid for which analyses, and what to do when they are not

# The planner picks a chart type, but that choice gets checked here against the analysis
# it actually produced. A time series over a non-temporal dimension, a map over sponsors,
# a grouped bar chart with nothing to group by: each one is caught and swapped for the
# sensible default, and the swap is written into meta.warnings

from __future__ import annotations

from app.analysis.dimensions import DIMENSIONS
from app.models.plan import (
    AnalysisPlan,
    GroupByAnalysis,
    HistogramAnalysis,
    KpiAnalysis,
    NetworkAnalysis,
    ScatterAnalysis,
    VisualizationType,
)

ALLOWED_TYPES: dict[str, tuple[VisualizationType, ...]] = {
    "group_by": (
        "bar_chart",
        "grouped_bar_chart",
        "stacked_bar_chart",
        "time_series",
        "geo_map",
        "table",
    ),
    "network": ("network_graph",),
    "scatter": ("scatter_plot",),
    "histogram": ("histogram",),
    "kpi": ("kpi", "table"),
}

# Dimensions where the values can be put on a map
GEO_DIMENSIONS = {"country"}


def default_visualization(plan: AnalysisPlan) -> VisualizationType:
    # The chart type that fits an analysis best, regardless of what was asked
    analysis = plan.analysis
    if isinstance(analysis, NetworkAnalysis):
        return "network_graph"
    if isinstance(analysis, ScatterAnalysis):
        return "scatter_plot"
    if isinstance(analysis, HistogramAnalysis):
        return "histogram"
    if isinstance(analysis, KpiAnalysis):
        return "kpi"

    assert isinstance(analysis, GroupByAnalysis)
    dimension = DIMENSIONS[analysis.dimension]
    if dimension.kind == "temporal":
        return "time_series"
    if dimension.id in GEO_DIMENSIONS:
        return "geo_map"
    if analysis.series_dimension:
        return "grouped_bar_chart"
    return "bar_chart"


def _incompatibility(plan: AnalysisPlan, requested: VisualizationType) -> str | None:
    # Say why the requested chart cannot render this plan, or None if it can
    analysis = plan.analysis
    allowed = ALLOWED_TYPES[analysis.kind]
    if requested not in allowed:
        return (
            f"{requested!r} cannot render a {analysis.kind!r} analysis "
            f"(valid: {', '.join(allowed)})"
        )

    if not isinstance(analysis, GroupByAnalysis):
        return None

    dimension = DIMENSIONS[analysis.dimension]
    if requested == "time_series" and dimension.kind != "temporal":
        return (
            f"a time series needs a temporal dimension, but {dimension.id!r} is "
            f"{dimension.kind}"
        )
    if requested == "geo_map" and dimension.id not in GEO_DIMENSIONS:
        return f"a map needs a geographic dimension, but {dimension.id!r} is not one"
    if requested in {"grouped_bar_chart", "stacked_bar_chart"} and not analysis.series_dimension:
        return f"{requested!r} needs a series_dimension to group by"
    return None


def resolve_visualization(plan: AnalysisPlan) -> tuple[VisualizationType, list[str]]:
    # Return the chart type to actually render, plus any warnings about swaps made.
    # Also upgrades bar_chart to grouped_bar_chart when there is a series dimension, so
    # a renderer never gets a single-series spec for data that has several series.
    warnings: list[str] = []
    requested = plan.visualization.type

    reason = _incompatibility(plan, requested)
    if reason is not None:
        fallback = default_visualization(plan)
        warnings.append(
            f"Requested visualization {requested!r} was replaced with {fallback!r}: {reason}."
        )
        return fallback, warnings

    analysis = plan.analysis
    if (
        isinstance(analysis, GroupByAnalysis)
        and analysis.series_dimension
        and requested == "bar_chart"
    ):
        warnings.append(
            "Promoted 'bar_chart' to 'grouped_bar_chart' because the analysis has a series "
            "dimension."
        )
        return "grouped_bar_chart", warnings

    return requested, warnings
