# Turns analysis results into the specs a frontend renders

# Each builder returns rows keyed by dimension and measure ids, and an encoding that
# names those same keys for each visual channel. A renderer reads encoding.x.field to
# find out which key holds the x value, instead of knowing where to look per chart type.

# Builders also hand back the citations they attached, so the caller can build the
# response-level citation index

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.analysis.aggregate import AggregationResult, Contribution
from app.analysis.citations import sample_citations
from app.analysis.dimensions import Dimension, get_dimension
from app.analysis.measures import Metric, get_measure, get_metric
from app.analysis.network import NetworkResult
from app.ctgov.normalize import TrialRecord
from app.models.plan import (
    HistogramAnalysis,
    KpiAnalysis,
    ScatterAnalysis,
    VisualizationType,
)
from app.models.response import (
    Channel,
    Citation,
    EdgeChannels,
    Encoding,
    NodeChannels,
    Visualization,
)

_KIND_TO_CHANNEL = {
    "nominal": "nominal",
    "ordinal": "ordinal",
    "temporal": "temporal",
    "quantitative": "quantitative",
}


@dataclass
class BuiltVisualization:
    # A finished chart spec plus every citation inside it

    visualization: Visualization
    citations: list[Citation] = field(default_factory=list)
    titles: dict[str, str] = field(default_factory=dict)
    # NCT ID to trial title, used to build the citation index


def _collect(
    contributions: Sequence[Contribution],
    source_field: str,
    limit: int,
    sink: BuiltVisualization,
) -> list[dict[str, Any]]:
    # Pick citations for one data point and record them on the sink
    citations = sample_citations(contributions, source_field=source_field, limit=limit)
    sink.citations.extend(citations)
    for contribution in contributions:
        sink.titles.setdefault(contribution.record.nct_id, contribution.record.brief_title)
    return [c.model_dump() for c in citations]


def _dimension_channel(dimension: Dimension) -> Channel:
    return Channel(
        field=dimension.id,
        type=_KIND_TO_CHANNEL[dimension.kind],  # type: ignore[arg-type]
        title=dimension.label,
    )


def build_group_by(
    result: AggregationResult,
    *,
    viz_type: VisualizationType,
    title: str,
    subtitle: str | None,
    citations_per_datum: int,
) -> BuiltVisualization:
    # Build bars, lines, maps or tables out of an aggregation
    dimension = result.dimension
    measure = result.measure
    built = BuiltVisualization(
        visualization=Visualization(
            type=viz_type, title=title, subtitle=subtitle, encoding=Encoding()
        )
    )

    rows: list[dict[str, Any]] = []
    for bucket in result.buckets:
        row: dict[str, Any] = {dimension.id: bucket.label, measure.id: bucket.value}
        row.update(bucket.extra)
        if result.series_dimension is not None:
            row[result.series_dimension.id] = bucket.series_label
        if bucket.share_pct is not None:
            row["share_pct"] = bucket.share_pct
        row["contributing_trial_count"] = bucket.trial_count
        if citations_per_datum:
            row["citations"] = _collect(
                bucket.contributions, dimension.source_field, citations_per_datum, built
            )
        rows.append(row)

    measure_channel = Channel(
        field=measure.id, type="quantitative", title=measure.label, unit=measure.unit
    )
    encoding = Encoding(x=_dimension_channel(dimension), y=measure_channel)
    if result.series_dimension is not None:
        encoding.series = _dimension_channel(result.series_dimension)

    if viz_type == "geo_map":
        # Both geographic and categorical channels are provided, so a client without map
        # support can fall back to bars from the same payload.
        encoding.location = Channel(field="country_iso3", type="geo", title="Country")
        encoding.color = measure_channel

    built.visualization.encoding = encoding
    built.visualization.data = rows
    return built


def build_network(
    result: NetworkResult,
    *,
    title: str,
    subtitle: str | None,
    citations_per_datum: int,
) -> BuiltVisualization:
    # Build the nodes and edges payload from a graph
    built = BuiltVisualization(
        visualization=Visualization(
            type="network_graph", title=title, subtitle=subtitle, encoding=Encoding()
        )
    )

    source_label = result.source_dimension.label
    target_label = result.target_dimension.label

    nodes: list[dict[str, Any]] = []
    for node in result.nodes:
        entry: dict[str, Any] = {
            "id": node.id,
            "label": node.label,
            "group": node.group,
            "group_label": source_label if node.group == result.source_dimension.id else target_label,
            "trial_count": node.trial_count,
            "degree": node.degree,
        }
        if citations_per_datum:
            source_field = (
                result.source_dimension.source_field
                if node.group == result.source_dimension.id
                else result.target_dimension.source_field
            )
            entry["citations"] = _collect(
                node.contributions, source_field, citations_per_datum, built
            )
        nodes.append(entry)

    edges: list[dict[str, Any]] = []
    for edge in result.edges:
        entry = {
            "source": edge.source,
            "target": edge.target,
            "weight": edge.weight,
            "contributing_trial_count": edge.weight,
        }
        if citations_per_datum:
            entry["citations"] = _collect(
                edge.contributions,
                f"{result.source_dimension.source_field} + {result.target_dimension.source_field}",
                citations_per_datum,
                built,
            )
        edges.append(entry)

    built.visualization.encoding = Encoding(
        node=NodeChannels(
            title=source_label if not result.is_bipartite else f"{source_label} / {target_label}"
        ),
        edge=EdgeChannels(
            title="Trials in common" if not result.is_bipartite else "Trials linking the two"
        ),
    )
    built.visualization.nodes = nodes
    built.visualization.edges = edges
    return built


def build_scatter(
    records: Sequence[TrialRecord],
    analysis: ScatterAnalysis,
    *,
    title: str,
    subtitle: str | None,
    citations_per_datum: int,
) -> tuple[BuiltVisualization, int]:
    # One point per trial. Returns the spec and how many trials were missing a value.
    # Points are sorted by NCT ID before the cap is applied, so if it does get cut short
    # the same trials are kept every time, not whichever came back first.
    x_metric = get_metric(analysis.x_metric)
    y_metric = get_metric(analysis.y_metric)
    color_dimension = (
        get_dimension(analysis.color_dimension) if analysis.color_dimension else None
    )

    built = BuiltVisualization(
        visualization=Visualization(
            type="scatter_plot", title=title, subtitle=subtitle, encoding=Encoding()
        )
    )

    usable: list[tuple[TrialRecord, float, float]] = []
    skipped = 0
    for record in records:
        x_value = x_metric.extract(record)
        y_value = y_metric.extract(record)
        if x_value is None or y_value is None:
            skipped += 1
            continue
        usable.append((record, x_value, y_value))

    usable.sort(key=lambda item: item[0].nct_id)
    rows: list[dict[str, Any]] = []
    for record, x_value, y_value in usable[: analysis.max_points]:
        row: dict[str, Any] = {
            "nct_id": record.nct_id,
            x_metric.id: x_value,
            y_metric.id: y_value,
            "label": record.brief_title,
        }
        if color_dimension is not None:
            values = color_dimension.extract(record)
            row[color_dimension.id] = values[0].label if values else "Unknown"
        if citations_per_datum:
            row["citations"] = _collect(
                [Contribution(record=record, excerpt=f"{x_metric.label}: {x_value:g}; "
                              f"{y_metric.label}: {y_value:g}")],
                f"{x_metric.source_field} + {y_metric.source_field}",
                1,
                built,
            )
        rows.append(row)

    encoding = Encoding(
        x=Channel(field=x_metric.id, type="quantitative", title=x_metric.label, unit=x_metric.unit),
        y=Channel(field=y_metric.id, type="quantitative", title=y_metric.label, unit=y_metric.unit),
    )
    if color_dimension is not None:
        encoding.color = _dimension_channel(color_dimension)

    built.visualization.encoding = encoding
    built.visualization.data = rows
    return built, skipped


def _linear_bins(low: float, high: float, count: int) -> list[float]:
    step = (high - low) / count
    return [low + step * i for i in range(count + 1)]


def _log_bins(low: float, high: float, count: int) -> list[float]:
    import math

    # Values at or below zero cannot be placed on a log scale; the caller filters them.
    low = max(low, 1.0)
    log_low, log_high = math.log10(low), math.log10(max(high, low * 10))
    step = (log_high - log_low) / count
    return [10 ** (log_low + step * i) for i in range(count + 1)]


def build_histogram(
    records: Sequence[TrialRecord],
    analysis: HistogramAnalysis,
    *,
    title: str,
    subtitle: str | None,
    citations_per_datum: int,
) -> tuple[BuiltVisualization, dict[str, int]]:
    # Bin a metric. Returns the spec plus how many trials were skipped
    metric: Metric = get_metric(analysis.metric)
    built = BuiltVisualization(
        visualization=Visualization(
            type="histogram", title=title, subtitle=subtitle, encoding=Encoding()
        )
    )

    values: list[tuple[TrialRecord, float]] = []
    skipped = 0
    for record in records:
        value = metric.extract(record)
        if value is None:
            skipped += 1
            continue
        values.append((record, value))

    stats = {"records_missing_metric": skipped, "records_clipped": 0}
    if not values:
        built.visualization.encoding = Encoding(
            x=Channel(field="bin", type="ordinal", title=metric.label, unit=metric.unit),
            y=Channel(field="trial_count", type="quantitative", title="Number of Trials",
                      unit="trials"),
        )
        return built, stats

    if analysis.log_scale:
        # A log axis cannot show zero, so those trials are excluded and reported.
        positive = [(r, v) for r, v in values if v > 0]
        stats["records_clipped"] += len(values) - len(positive)
        values = positive

    if analysis.max_value is not None:
        clipped = [(r, v) for r, v in values if v <= analysis.max_value]
        stats["records_clipped"] += len(values) - len(clipped)
        values = clipped

    if not values:
        built.visualization.encoding = Encoding(
            x=Channel(field="bin", type="ordinal", title=metric.label, unit=metric.unit),
            y=Channel(field="trial_count", type="quantitative", title="Number of Trials",
                      unit="trials"),
        )
        return built, stats

    numbers = [v for _, v in values]
    low, high = min(numbers), max(numbers)
    if low == high:
        high = low + 1
    edges = (
        _log_bins(low, high, analysis.bin_count)
        if analysis.log_scale
        else _linear_bins(low, high, analysis.bin_count)
    )
    if metric.is_integer:
        # A count cannot fall between 1 and 1.29, so fractional edges over an integer
        # metric produce empty bins labelled "1–1". Snapping to integers and dropping
        # duplicates yields honest bins at the cost of returning fewer than bin_count.
        edges = sorted({round(edge) for edge in edges})
        if len(edges) < 2:
            edges = [round(low), round(low) + 1]

    buckets: list[list[TrialRecord]] = [[] for _ in range(len(edges) - 1)]
    for record, value in values:
        index = 0
        while index < len(buckets) - 1 and value >= edges[index + 1]:
            index += 1
        buckets[index].append(record)

    rows: list[dict[str, Any]] = []
    for index, bucket in enumerate(buckets):
        lower, upper = edges[index], edges[index + 1]
        if metric.is_integer:
            # Bins are half-open [lower, upper) except the last, so the largest value a
            # bin can hold is upper-1; labelling it "upper" would overlap the next bin.
            top = int(upper) if index == len(buckets) - 1 else int(upper) - 1
            label = f"{int(lower):,}" if int(lower) >= top else f"{int(lower):,}–{top:,}"
        else:
            label = f"{lower:,.1f}–{upper:,.1f}"
        row: dict[str, Any] = {
            "bin": label,
            "bin_start": round(lower, 4),
            "bin_end": round(upper, 4),
            "trial_count": len(bucket),
            "contributing_trial_count": len(bucket),
        }
        if citations_per_datum and bucket:
            row["citations"] = _collect(
                [
                    Contribution(
                        record=r,
                        excerpt=f"{metric.label}: {metric.extract(r):g}",  # type: ignore[arg-type]
                    )
                    for r in bucket
                ],
                metric.source_field,
                citations_per_datum,
                built,
            )
        rows.append(row)

    built.visualization.encoding = Encoding(
        x=Channel(field="bin", type="ordinal", title=metric.label, unit=metric.unit),
        y=Channel(field="trial_count", type="quantitative", title="Number of Trials",
                  unit="trials"),
    )
    built.visualization.data = rows
    return built, stats


def build_kpi(
    records: Sequence[TrialRecord],
    analysis: KpiAnalysis,
    *,
    title: str,
    subtitle: str | None,
    citations_per_datum: int,
    breakdown: AggregationResult | None,
) -> BuiltVisualization:
    # A single headline number, with optional supporting rows under it.
    # This is the shape for questions a chart would not improve: "how many trials is
    # Pfizer running for lung cancer?" wants a number, not one lonely bar.
    measure = get_measure(analysis.measure)
    built = BuiltVisualization(
        visualization=Visualization(
            type="kpi", title=title, subtitle=subtitle, encoding=Encoding()
        )
    )

    headline: dict[str, Any] = {
        "label": measure.label,
        measure.id: measure.compute(records),
        "unit": measure.unit,
        "contributing_trial_count": len(records),
    }
    if citations_per_datum:
        headline["citations"] = _collect(
            [Contribution(record=r, excerpt=r.nct_id) for r in records],
            "protocolSection.identificationModule.nctId",
            citations_per_datum,
            built,
        )

    rows = [headline]
    if breakdown is not None:
        for bucket in breakdown.buckets:
            row: dict[str, Any] = {
                "label": bucket.label,
                measure.id: bucket.value,
                "unit": measure.unit,
                "group": breakdown.dimension.id,
                "contributing_trial_count": bucket.trial_count,
            }
            if bucket.share_pct is not None:
                row["share_pct"] = bucket.share_pct
            if citations_per_datum:
                row["citations"] = _collect(
                    bucket.contributions,
                    breakdown.dimension.source_field,
                    citations_per_datum,
                    built,
                )
            rows.append(row)

    built.visualization.encoding = Encoding(
        x=Channel(field="label", type="nominal", title="Measure"),
        y=Channel(field=measure.id, type="quantitative", title=measure.label, unit=measure.unit),
    )
    built.visualization.data = rows
    return built
