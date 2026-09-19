# Runs a validated plan against ClinicalTrials.gov. No language model runs in this file.

# This is the deterministic half of the service. It takes a plan, fetches the trials it
# describes, computes the numbers, and builds the response. Every figure the caller sees
# comes from this file, out of bytes the API returned.


from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.analysis.aggregate import AggregationResult, Bucket, Contribution, aggregate
from app.analysis.dimensions import DIMENSIONS, get_dimension, required_api_fields
from app.analysis.measures import get_measure, get_metric
from app.analysis.network import build_network
from app.ctgov.client import CTGovClient, FetchResult
from app.ctgov.enums import humanize
from app.ctgov.normalize import TrialRecord
from app.ctgov.query_builder import value_clause
from app.models.plan import (
    AnalysisPlan,
    GroupByAnalysis,
    HistogramAnalysis,
    KpiAnalysis,
    NetworkAnalysis,
    ScatterAnalysis,
    TrialFilterSpec,
)
from app.models.request import VisualizeRequest
from app.models.response import (
    CohortCoverage,
    Coverage,
    FiltersApplied,
    MeasureInfo,
    ResponseMeta,
    Visualization,
    VisualizeResponse,
)
from app.viz import builders
from app.viz.compatibility import resolve_visualization

logger = logging.getLogger(__name__)

# Request field -> the TrialFilterSpec field it constrains.
_USER_FILTER_MAP: dict[str, str] = {
    "drug_name": "interventions",
    "condition": "conditions",
    "sponsor": "sponsors",
    "country": "countries",
    "trial_phase": "phases",
    "status": "statuses",
    "study_type": "study_types",
    "intervention_type": "intervention_types",
    "sponsor_class": "sponsor_classes",
}

_MEASURE_API_FIELDS: dict[str, tuple[str, ...]] = {
    "total_enrollment": ("EnrollmentCount", "EnrollmentType"),
    "median_enrollment": ("EnrollmentCount", "EnrollmentType"),
    "mean_enrollment": ("EnrollmentCount", "EnrollmentType"),
    "distinct_sponsor_count": ("LeadSponsorName",),
    "distinct_drug_count": ("InterventionMeshTerm",),
}
# Extra API fields a measure needs, on top of whatever its dimensions already ask for


@dataclass
class ExecutionOutcome:
    # Everything the API layer needs to build a response

    response: VisualizeResponse
    warnings: list[str] = field(default_factory=list)


def enforce_user_filters(
    plan: AnalysisPlan, request: VisualizeRequest
) -> tuple[dict[str, Any], list[str]]:
    # Apply the caller's structured fields to every cohort in the plan.
    # Changes the plan in place, and returns which filters were actually applied plus any
    # warnings. A field the cohorts already differ on is left alone, because that
    # difference is the comparison the user asked for.
    enforced: dict[str, Any] = {}
    warnings: list[str] = []
    cohorts = plan.retrieval.cohorts

    for request_field, spec_field in _USER_FILTER_MAP.items():
        value = getattr(request, request_field)
        if not value:
            continue
        existing = {tuple(getattr(c.filters, spec_field)) for c in cohorts}
        if len(cohorts) > 1 and len(existing) > 1:
            warnings.append(
                f"Request field {request_field!r} was not applied: the cohorts being compared "
                f"are distinguished by {spec_field}, and overriding it would collapse the "
                "comparison."
            )
            continue
        for cohort in cohorts:
            setattr(cohort.filters, spec_field, list(value))
        enforced[request_field] = list(value)

    for request_field, spec_field in (("start_year", "start_year_min"), ("end_year", "start_year_max")):
        value = getattr(request, request_field)
        if value is None:
            continue
        existing_years = {getattr(c.filters, spec_field) for c in cohorts}
        if len(cohorts) > 1 and len(existing_years) > 1:
            warnings.append(
                f"Request field {request_field!r} was not applied: the cohorts differ on it."
            )
            continue
        for cohort in cohorts:
            setattr(cohort.filters, spec_field, value)
        enforced[request_field] = value

    return enforced, warnings


def _inferred_filters(plan: AnalysisPlan, enforced: dict[str, Any]) -> dict[str, Any]:
    # The filters the planner worked out itself, with the caller's own ones removed
    enforced_spec_fields = {
        _USER_FILTER_MAP[k] for k in enforced if k in _USER_FILTER_MAP
    }
    if "start_year" in enforced:
        enforced_spec_fields.add("start_year_min")
    if "end_year" in enforced:
        enforced_spec_fields.add("start_year_max")

    out: dict[str, Any] = {}
    for cohort in plan.retrieval.cohorts:
        active = {
            name: value
            for name, value in cohort.filters.model_dump(exclude_none=True).items()
            if value not in ([], None) and name not in enforced_spec_fields
        }
        out[cohort.name] = active
    return out


def _projection_for(plan: AnalysisPlan) -> tuple[str, ...]:
    # Exactly which API fields this plan needs
    fields = set(required_api_fields([d for d in plan.dimension_ids if d in DIMENSIONS]))
    for metric_id in plan.metric_ids:
        fields.update(get_metric(metric_id).api_fields)

    # A measure may read a field that no dimension in the plan requested.
    if isinstance(plan.analysis, (KpiAnalysis, GroupByAnalysis)):
        fields.update(_MEASURE_API_FIELDS.get(plan.analysis.measure, ()))
    return tuple(sorted(fields))


def _can_use_exact_counts(plan: AnalysisPlan, fetches: list[FetchResult]) -> bool:
    # Whether the per-bucket counting strategy both applies here and would actually help
    analysis = plan.analysis
    if not isinstance(analysis, GroupByAnalysis) or analysis.measure != "trial_count":
        return False
    if analysis.series_dimension not in (None, "cohort"):
        # A cross-product of buckets would need |dimension| x |series| requests.
        return False
    if not get_dimension(analysis.dimension).supports_exact_counts:
        return False
    # Only worth the extra requests when downloading everything fell short.
    return any(f.truncated for f in fetches)


async def _exact_count_buckets(
    client: CTGovClient,
    plan: AnalysisPlan,
    analysis: GroupByAnalysis,
    citations_per_datum: int,
) -> tuple[list[Bucket], list[dict[str, str]]]:
    # Ask the API for the size of every bucket, plus a few trials to cite.
    # One request per cohort and value. Each one returns the true total for that bucket
    # and a handful of records, so the plotted numbers are exact even when the full result
    # set is too big to download.
    dimension = get_dimension(analysis.dimension)
    assert dimension.enum_values and dimension.essie_area

    jobs: list[tuple[str, str, TrialFilterSpec]] = [
        (cohort.name, value, cohort.filters)
        for cohort in plan.retrieval.cohorts
        for value in dimension.enum_values
    ]

    results = await asyncio.gather(
        *(
            client.count_and_sample(
                filters,
                extra_advanced=value_clause(dimension.essie_area, value),
                sample_size=max(citations_per_datum, 1),
                cohort=cohort_name,
            )
            for cohort_name, value, filters in jobs
        )
    )

    buckets: list[Bucket] = []
    requests: list[dict[str, str]] = []
    multi_cohort = plan.retrieval.is_comparison or analysis.series_dimension == "cohort"

    for (cohort_name, value, _), (total, samples, params) in zip(jobs, results, strict=True):
        requests.append(params)
        if total == 0:
            continue
        buckets.append(
            Bucket(
                key=value,
                label=humanize(value),
                value=total,
                total_trials=total,
                contributions=[Contribution(record=r, excerpt=value) for r in samples],
                series_key=cohort_name if multi_cohort else None,
                series_label=cohort_name if multi_cohort else None,
            )
        )
    return buckets, requests


def _order_exact_buckets(
    buckets: list[Bucket], analysis: GroupByAnalysis, dimension_id: str
) -> list[Bucket]:
    # Apply the plan's sorting and top_k to buckets that came from exact counts
    dimension = get_dimension(dimension_id)
    totals: dict[str, float] = {}
    for bucket in buckets:
        totals[bucket.key] = totals.get(bucket.key, 0.0) + float(bucket.value or 0)

    if analysis.sort_by == "category" and dimension.category_order:
        order = {key: i for i, key in enumerate(dimension.category_order)}
        keys = sorted(totals, key=lambda k: order.get(k, len(order)))
    elif analysis.sort_by == "category":
        keys = sorted(totals)
    else:
        keys = sorted(totals, key=lambda k: -totals[k])
    if analysis.sort_order == "asc" and analysis.sort_by == "value":
        keys.reverse()
    elif analysis.sort_order == "desc" and analysis.sort_by == "category":
        keys.reverse()

    if analysis.top_k is not None:
        keep = set(sorted(totals, key=lambda k: -totals[k])[: analysis.top_k])
        keys = [k for k in keys if k in keep]

    position = {key: i for i, key in enumerate(keys)}
    kept = [b for b in buckets if b.key in position]
    kept.sort(key=lambda b: (position[b.key], b.series_label or ""))

    grand_total = sum(float(b.value or 0) for b in kept)
    if grand_total > 0:
        for bucket in kept:
            bucket.share_pct = round(float(bucket.value or 0) / grand_total * 100, 2)
    return kept


class PlanExecutor:
    # Runs a validated plan and produces the response

    def __init__(self, client: CTGovClient, default_max_studies: int) -> None:
        self.client = client
        self.default_max_studies = default_max_studies

    async def execute(
        self, plan: AnalysisPlan, request: VisualizeRequest, extra_warnings: list[str] | None = None
    ) -> VisualizeResponse:
        # The whole pipeline, in order:
        # 1. apply the caller's filters over whatever the planner inferred
        # 2. work out which API fields the plan needs
        # 3. fetch every cohort at once
        # 4. flatten the records and note how much of the data actually got received
        # 5. if nothing matched, say so instead of returning an empty chart
        # 6. run the analysis, branching on analysis.kind
        # 7. check the chart type fits, then build it
        # 8. assemble meta, warnings and citations into the response
        warnings = list(extra_warnings or [])

        enforced, filter_warnings = enforce_user_filters(plan, request)
        warnings.extend(filter_warnings)

        max_studies = request.options.max_studies or self.default_max_studies
        projection = _projection_for(plan)

        fetches = await asyncio.gather(
            *(
                self.client.fetch(
                    cohort.filters,
                    fields=projection,
                    max_studies=max_studies,
                    cohort=cohort.name,
                )
                for cohort in plan.retrieval.cohorts
            )
        )

        records: list[TrialRecord] = [r for fetch in fetches for r in fetch.records]
        ctgov_requests: list[dict[str, str]] = [p for fetch in fetches for p in fetch.requests]
        per_cohort = [
            CohortCoverage(
                name=cohort.name,
                total_matching=fetch.total_count,
                analyzed=fetch.analyzed_count,
                truncated=fetch.truncated,
            )
            for cohort, fetch in zip(plan.retrieval.cohorts, fetches, strict=True)
        ]

        filters_applied = FiltersApplied(
            user=enforced, inferred=_inferred_filters(plan, enforced)
        )

        if not records:
            return self._empty_response(
                plan, request, per_cohort, ctgov_requests, filters_applied, warnings
            )

        strategy: str = "fetch_and_aggregate"
        analysis = plan.analysis
        citations = request.options.citations_per_datum if request.options.include_citations else 0

        # Analysis
        aggregation: AggregationResult | None = None
        built: builders.BuiltVisualization
        counting_semantics = ""
        measure_info: MeasureInfo | None = None
        time_granularity = None
        sort_info = None

        if isinstance(analysis, GroupByAnalysis):
            dimension = get_dimension(analysis.dimension)
            measure = get_measure(analysis.measure)
            series_dimension = (
                get_dimension(analysis.series_dimension) if analysis.series_dimension else None
            )

            if _can_use_exact_counts(plan, list(fetches)):
                strategy = "exact_counts"
                buckets, probe_requests = await _exact_count_buckets(
                    self.client, plan, analysis, citations
                )
                ctgov_requests.extend(probe_requests)
                buckets = _order_exact_buckets(buckets, analysis, analysis.dimension)
                aggregation = AggregationResult(
                    buckets=buckets,
                    dimension=dimension,
                    measure=measure,
                    series_dimension=series_dimension,
                    total_records=sum(c.total_matching for c in per_cohort),
                )
                warnings.append(
                    "Result set exceeded the retrieval cap, so bucket totals were obtained "
                    "directly from the API and are exact; citations sample a few trials per "
                    "bucket rather than listing all of them."
                )
            else:
                aggregation = aggregate(
                    records,
                    dimension=dimension,
                    measure=measure,
                    series_dimension=series_dimension,
                    top_k=analysis.top_k,
                    sort_by=analysis.sort_by,
                    sort_order=analysis.sort_order,
                    include_unknown=analysis.include_unknown,
                    min_value=analysis.min_value,
                )

            viz_type, viz_warnings = resolve_visualization(plan)
            warnings.extend(viz_warnings)
            built = builders.build_group_by(
                aggregation,
                viz_type=viz_type,
                title=plan.visualization.title,
                subtitle=plan.visualization.subtitle,
                citations_per_datum=citations,
            )
            counting_semantics = aggregation.counting_semantics
            measure_info = MeasureInfo(id=measure.id, label=measure.label, unit=measure.unit)
            sort_info = {"by": analysis.sort_by, "order": analysis.sort_order}
            if dimension.kind == "temporal":
                time_granularity = {
                    "start_year": "year",
                    "completion_year": "year",
                    "start_quarter": "quarter",
                    "start_month": "month",
                }.get(dimension.id)

        elif isinstance(analysis, NetworkAnalysis):
            network = build_network(
                records,
                source_dimension=get_dimension(analysis.source_dimension),
                target_dimension=get_dimension(analysis.target_dimension),
                min_edge_weight=analysis.min_edge_weight,
                max_nodes=analysis.max_nodes,
                top_k_per_side=analysis.top_k_per_side,
            )
            built = builders.build_network(
                network,
                title=plan.visualization.title,
                subtitle=plan.visualization.subtitle,
                citations_per_datum=citations,
            )
            counting_semantics = network.counting_semantics
            if network.nodes_omitted or network.edges_omitted:
                warnings.append(
                    f"Graph pruned for readability: {network.nodes_omitted:,} nodes and "
                    f"{network.edges_omitted:,} edges below the thresholds were omitted "
                    f"(min_edge_weight={analysis.min_edge_weight}, max_nodes={analysis.max_nodes})."
                )
            if network.records_skipped_for_fanout:
                warnings.append(
                    f"{network.records_skipped_for_fanout:,} trials listed more than 40 entities "
                    "and were excluded from edge building to avoid distorting the graph."
                )
            if not network.edges:
                warnings.append(
                    "No pair of entities co-occurred often enough to meet min_edge_weight="
                    f"{analysis.min_edge_weight}; try lowering it."
                )

        elif isinstance(analysis, ScatterAnalysis):
            built, skipped = builders.build_scatter(
                records,
                analysis,
                title=plan.visualization.title,
                subtitle=plan.visualization.subtitle,
                citations_per_datum=citations,
            )
            counting_semantics = "Each point is one trial."
            if skipped:
                warnings.append(
                    f"{skipped:,} trials were omitted because they did not report both "
                    f"{analysis.x_metric} and {analysis.y_metric}."
                )
            if len(records) - skipped > analysis.max_points:
                warnings.append(
                    f"Showing the first {analysis.max_points:,} of "
                    f"{len(records) - skipped:,} plottable trials, ordered by NCT ID."
                )

        elif isinstance(analysis, HistogramAnalysis):
            built, stats = builders.build_histogram(
                records,
                analysis,
                title=plan.visualization.title,
                subtitle=plan.visualization.subtitle,
                citations_per_datum=citations,
            )
            metric = get_metric(analysis.metric)
            counting_semantics = (
                f"Each trial falls in exactly one {metric.label.lower()} bin."
            )
            measure_info = MeasureInfo(id="trial_count", label="Number of Trials", unit="trials")
            if stats["records_missing_metric"]:
                warnings.append(
                    f"{stats['records_missing_metric']:,} trials did not report "
                    f"{analysis.metric} and are not in the distribution."
                )
            if stats["records_clipped"]:
                warnings.append(
                    f"{stats['records_clipped']:,} trials fell outside the plotted range and "
                    "were excluded from the bins."
                )

        else:
            assert isinstance(analysis, KpiAnalysis)
            breakdown = None
            if analysis.breakdown_dimension:
                breakdown = aggregate(
                    records,
                    dimension=get_dimension(analysis.breakdown_dimension),
                    measure=get_measure(analysis.measure),
                    top_k=analysis.breakdown_top_k,
                    sort_by="value",
                    sort_order="desc",
                )
            built = builders.build_kpi(
                records,
                analysis,
                title=plan.visualization.title,
                subtitle=plan.visualization.subtitle,
                citations_per_datum=citations,
                breakdown=breakdown,
            )
            measure = get_measure(analysis.measure)
            measure_info = MeasureInfo(id=measure.id, label=measure.label, unit=measure.unit)
            counting_semantics = (
                breakdown.counting_semantics
                if breakdown
                else f"A single {measure.label.lower()} over all matching trials."
            )

        # Coverage and assembly
        total_matching = sum(c.total_matching for c in per_cohort)
        analyzed = sum(c.analyzed for c in per_cohort)
        truncated = any(c.truncated for c in per_cohort)

        if truncated and strategy == "fetch_and_aggregate":
            warnings.append(
                f"Analyzed {analyzed:,} of {total_matching:,} matching trials (retrieval cap). "
                "Figures describe the analyzed subset; raise options.max_studies or narrow the "
                "filters for full coverage."
            )

        coverage = Coverage(
            strategy=strategy,  # type: ignore[arg-type]
            total_matching=total_matching,
            analyzed=analyzed if strategy == "fetch_and_aggregate" else total_matching,
            truncated=truncated and strategy == "fetch_and_aggregate",
            per_cohort=per_cohort,
            records_missing_dimension=aggregation.records_missing_dimension if aggregation else 0,
            records_missing_measure=aggregation.records_missing_measure if aggregation else 0,
            categories_omitted=aggregation.categories_omitted if aggregation else 0,
        )

        if aggregation and aggregation.records_missing_dimension and not getattr(
            analysis, "include_unknown", False
        ):
            warnings.append(
                f"{aggregation.records_missing_dimension:,} trials did not report "
                f"{aggregation.dimension.label.lower()} and are excluded from the buckets."
            )

        meta = ResponseMeta(
            interpretation=plan.interpretation,
            assumptions=plan.assumptions,
            filters_applied=filters_applied,
            counting_semantics=counting_semantics,
            coverage=coverage,
            measure=measure_info,
            sort=sort_info,
            time_granularity=time_granularity,  # type: ignore[arg-type]
            ctgov_requests=ctgov_requests,
            warnings=warnings,
        )

        from app.analysis.citations import index_citations

        return VisualizeResponse(
            status="ok",
            question=request.query,
            visualization=built.visualization,
            meta=meta,
            plan=plan if request.options.include_plan else None,
            citation_index=index_citations(built.citations, built.titles),
        )

    def _empty_response(
        self,
        plan: AnalysisPlan,
        request: VisualizeRequest,
        per_cohort: list[CohortCoverage],
        ctgov_requests: list[dict[str, str]],
        filters_applied: FiltersApplied,
        warnings: list[str],
    ) -> VisualizeResponse:
        # Nothing matched. Say so and include the query that was run, rather than
        # returning an empty chart that looks like a real result.
        warnings.append(
            "No trials matched these filters, so no visualization was produced. The exact "
            "queries sent are in meta.ctgov_requests; try broadening the terms or removing "
            "a filter."
        )
        return VisualizeResponse(
            status="no_data",
            question=request.query,
            visualization=None,
            meta=ResponseMeta(
                interpretation=plan.interpretation,
                assumptions=plan.assumptions,
                filters_applied=filters_applied,
                counting_semantics="No trials matched.",
                coverage=Coverage(
                    strategy="fetch_and_aggregate",
                    total_matching=0,
                    analyzed=0,
                    truncated=False,
                    per_cohort=per_cohort,
                ),
                ctgov_requests=ctgov_requests,
                warnings=warnings,
            ),
            plan=plan if request.options.include_plan else None,
        )
