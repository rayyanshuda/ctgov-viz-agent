# The analysis plan: what the language model produces

# This schema is the line between the model half and the deterministic half. The planner
# picks what to ask and how to slice it. It doesn't supply a count, a trial ID, or a data
# point, because all of that gets computed later from what the API returns.

# Three things:
# Closed lists: dimensions, measures, metrics and filter values are checked against the
# registries, so an invented "sponsor_country" or a misremembered "PHASE_III" fails
# instead of matching nothing.

# extra="forbid": a plan with an unexpected key is rejected, which catches the model making up a parameter.

# A tagged analysis union: the "kind" decides which fields must be there, so a network
# plan cannot leave out its endpoints.

# Validation errors get handed straight back to the model to fix (see agent/planner.py),
# which turns most of these into a self-correction (so the user doesn't see them)

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    WithJsonSchema,
    model_validator,
)

from app.analysis.dimensions import DIMENSION_IDS, DIMENSIONS, TEMPORAL_DIMENSION_IDS
from app.analysis.measures import MEASURE_IDS, METRIC_IDS
from app.ctgov.enums import (
    INTERVENTION_TYPES,
    PHASES,
    SPONSOR_CLASSES,
    STATUSES,
    STUDY_TYPES,
)


def _in_registry(name: str, valid: tuple[str, ...]):
    def _validate(value: str) -> str:
        if value not in valid:
            raise ValueError(f"unknown {name} {value!r}; valid options are: {', '.join(valid)}")
        return value

    return _validate


def _coerce_json_list(value: object) -> object:
    # Accept a JSON string, or a plain string, where a list was expected.
    # The model sometimes sends a nested array as a string inside tool arguments. It is
    # an escaping quirk, not a reasoning mistake, so fixing it here avoids wasting a
    # repair round trip. The contents still get validated normally afterwards, so this
    # loosens the wire format
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            # raw_decode parses a valid JSON prefix and tolerates trailing characters.
            parsed, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            return value
        return parsed if isinstance(parsed, list) else value

    # An empty sentence is one item, not a malformed list.
    return [text]


StringList = Annotated[list[str], BeforeValidator(_coerce_json_list)]


DimensionId = Annotated[
    str,
    AfterValidator(_in_registry("dimension", DIMENSION_IDS)),
    WithJsonSchema({"type": "string", "enum": list(DIMENSION_IDS)}),
]
MeasureId = Annotated[
    str,
    AfterValidator(_in_registry("measure", MEASURE_IDS)),
    WithJsonSchema({"type": "string", "enum": list(MEASURE_IDS)}),
]
MetricId = Annotated[
    str,
    AfterValidator(_in_registry("metric", METRIC_IDS)),
    WithJsonSchema({"type": "string", "enum": list(METRIC_IDS)}),
]

Phase = Literal["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA"]
Status = Literal[
    "ACTIVE_NOT_RECRUITING",
    "COMPLETED",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "SUSPENDED",
    "TERMINATED",
    "WITHDRAWN",
    "AVAILABLE",
    "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE",
    "APPROVED_FOR_MARKETING",
    "WITHHELD",
    "UNKNOWN",
]
StudyType = Literal["INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS"]
InterventionTypeEnum = Literal[
    "BEHAVIORAL",
    "BIOLOGICAL",
    "COMBINATION_PRODUCT",
    "DEVICE",
    "DIAGNOSTIC_TEST",
    "DIETARY_SUPPLEMENT",
    "DRUG",
    "GENETIC",
    "PROCEDURE",
    "RADIATION",
    "OTHER",
]
SponsorClass = Literal[
    "NIH", "FED", "OTHER_GOV", "INDIV", "INDUSTRY", "NETWORK", "AMBIG", "OTHER", "UNKNOWN"
]

VisualizationType = Literal[
    "bar_chart",
    "grouped_bar_chart",
    "stacked_bar_chart",
    "time_series",
    "scatter_plot",
    "histogram",
    "geo_map",
    "network_graph",
    "kpi",
    "table",
]

# testing check: these Literals duplicate the enum tuples for static typing, so assert
# they have not drifted from the authoritative vocabularies.
assert set(Phase.__args__) == set(PHASES)
assert set(Status.__args__) == set(STATUSES)
assert set(StudyType.__args__) == set(STUDY_TYPES)
assert set(InterventionTypeEnum.__args__) == set(INTERVENTION_TYPES)
assert set(SponsorClass.__args__) == set(SPONSOR_CLASSES)


class StrictModel(BaseModel):
    # base for every plan model: unknown keys are an error

    model_config = ConfigDict(extra="forbid")


class TrialFilterSpec(StrictModel):
    # which trials to retrieve: maps onto ClinicalTrials.gov query parameters

    conditions: StringList = Field(
        default_factory=list,
        description="Disease or condition terms, e.g. ['melanoma']. Combined with OR.",
    )
    interventions: StringList = Field(
        default_factory=list,
        description="Drug or intervention terms, e.g. ['pembrolizumab']. Combined with OR.",
    )
    sponsors: StringList = Field(
        default_factory=list, description="Sponsor or collaborator names, e.g. ['Pfizer']."
    )
    terms: StringList = Field(
        default_factory=list,
        description="General free-text search terms, for anything the other fields do not cover.",
    )
    locations: StringList = Field(
        default_factory=list, description="Location search terms, e.g. ['Germany', 'Boston']."
    )

    phases: list[Phase] = Field(default_factory=list, description="Restrict to these phases.")
    statuses: list[Status] = Field(
        default_factory=list, description="Restrict to these recruitment statuses."
    )
    study_types: list[StudyType] = Field(
        default_factory=list, description="Restrict to these study types."
    )
    intervention_types: list[InterventionTypeEnum] = Field(
        default_factory=list, description="Restrict to these intervention types."
    )
    sponsor_classes: list[SponsorClass] = Field(
        default_factory=list, description="Restrict to these sponsor categories."
    )
    countries: StringList = Field(
        default_factory=list,
        description="Restrict to trials with a site in these countries. Use full names as "
        "ClinicalTrials.gov spells them, e.g. 'United States', 'South Korea'.",
    )

    start_year_min: int | None = Field(
        default=None, ge=1900, le=2100, description="Earliest trial start year, inclusive."
    )
    start_year_max: int | None = Field(
        default=None, ge=1900, le=2100, description="Latest trial start year, inclusive."
    )
    has_results: bool | None = Field(
        default=None, description="Restrict to trials that have (or have not) posted results."
    )

    @model_validator(mode="after")
    def _check(self) -> TrialFilterSpec:
        if (
            self.start_year_min is not None
            and self.start_year_max is not None
            and self.start_year_min > self.start_year_max
        ):
            raise ValueError("start_year_min must not be greater than start_year_max")
        if not self.has_any_constraint:
            raise ValueError(
                "a cohort needs at least one filter; an unconstrained query would match the "
                "entire 600,000-study registry"
            )
        return self

    @property
    def has_any_constraint(self) -> bool:
        return any(
            [
                self.conditions,
                self.interventions,
                self.sponsors,
                self.terms,
                self.locations,
                self.phases,
                self.statuses,
                self.study_types,
                self.intervention_types,
                self.sponsor_classes,
                self.countries,
                self.start_year_min is not None,
                self.start_year_max is not None,
                self.has_results is not None,
            ]
        )


class Cohort(StrictModel):
    # A named group of trials to retrieve

    # multiple cohorts are how every comparison question is expressed ("pembrolizumab vs
    # nivolumab", "trials in Germany vs Japan", "Pfizer vs Novartis"). Each is fetched
    # separately and tagged, so the "cohort" dimension can be used as a series to
    # produce a grouped chart. This keeps comparisons inside the general pipeline instead
    # of needing a special case.

    name: str = Field(
        min_length=1,
        max_length=80,
        description="Short label shown in the legend, e.g. 'Pembrolizumab'.",
    )
    filters: TrialFilterSpec


class RetrievalSpec(StrictModel):
    """Everything needed to fetch the underlying trials."""

    cohorts: list[Cohort] = Field(
        min_length=1,
        max_length=5,
        description="One cohort for a simple question; two or more to compare groups.",
    )

    @property
    def is_comparison(self) -> bool:
        return len(self.cohorts) > 1

    @model_validator(mode="after")
    def _unique_names(self) -> RetrievalSpec:
        names = [c.name.strip().lower() for c in self.cohorts]
        if len(set(names)) != len(names):
            raise ValueError("cohort names must be unique")
        return self


class GroupByAnalysis(StrictModel):
    # Group trials by a dimension and compute a measure (bars, lines, maps, tables)

    kind: Literal["group_by"] = "group_by"
    dimension: DimensionId = Field(description="The dimension forming the primary axis.")
    series_dimension: DimensionId | None = Field(
        default=None,
        description="Optional second dimension producing one series per value. Use 'cohort' "
        "to compare the cohorts defined in retrieval.",
    )
    measure: MeasureId = Field(default="trial_count", description="What to compute per bucket.")
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Keep only the top K buckets by value. Required in spirit for "
        "high-cardinality dimensions like lead_sponsor or intervention_mesh.",
    )
    sort_by: Literal["value", "category"] = Field(
        default="value",
        description="'value' ranks buckets by the measure; 'category' uses the dimension's "
        "natural order (chronological for dates, Phase 1..4 for phases).",
    )
    sort_order: Literal["asc", "desc"] = "desc"
    include_unknown: bool = Field(
        default=False,
        description="Whether to keep the bucket of trials that did not report this field.",
    )
    min_value: float | None = Field(
        default=None, description="Drop buckets whose measure falls below this threshold."
    )

    @model_validator(mode="after")
    def _check(self) -> GroupByAnalysis:
        if self.series_dimension == self.dimension:
            raise ValueError("series_dimension must differ from dimension")
        return self


class NetworkAnalysis(StrictModel):
    # Build a graph linking two entity types that co-occur within the same trial.

    # Set "source" and "target" to different dimensions for a bipartite graph
    # (sponsors to drugs); and set them to the same dimension for a co-occurrence graph
    # (drugs studied together in combination trials).

    kind: Literal["network"] = "network"
    source_dimension: DimensionId = Field(description="Dimension supplying source nodes.")
    target_dimension: DimensionId = Field(description="Dimension supplying target nodes.")
    min_edge_weight: int = Field(
        default=2,
        ge=1,
        le=1000,
        description="Drop edges supported by fewer than this many trials. Values above 1 cut "
        "the long tail of one-off links that makes a graph unreadable.",
    )
    max_nodes: int = Field(
        default=60,
        ge=2,
        le=300,
        description="Cap on rendered nodes, keeping the highest-degree ones.",
    )
    top_k_per_side: int | None = Field(
        default=None,
        ge=2,
        le=200,
        description="Restrict each side to its most frequent entities before linking.",
    )

    @model_validator(mode="after")
    def _check(self) -> NetworkAnalysis:
        eligible = sorted(d.id for d in DIMENSIONS.values() if d.network_eligible)
        for field_name in ("source_dimension", "target_dimension"):
            dimension = DIMENSIONS[getattr(self, field_name)]
            if not dimension.network_eligible:
                raise ValueError(
                    f"{field_name} {dimension.id!r} is not an entity dimension and would "
                    f"produce a dense, uninformative graph; use one of: {', '.join(eligible)}"
                )
        return self


class ScatterAnalysis(StrictModel):
    # Plot one point per trial across two metrics

    kind: Literal["scatter"] = "scatter"
    x_metric: MetricId
    y_metric: MetricId
    color_dimension: DimensionId | None = Field(
        default=None, description="Optional dimension colouring the points."
    )
    max_points: int = Field(default=1000, ge=10, le=5000)

    @model_validator(mode="after")
    def _check(self) -> ScatterAnalysis:
        if self.x_metric == self.y_metric:
            raise ValueError("x_metric and y_metric must differ")
        return self


class HistogramAnalysis(StrictModel):
    # Bin one metric across trials

    kind: Literal["histogram"] = "histogram"
    metric: MetricId
    bin_count: int = Field(default=20, ge=3, le=100)
    max_value: float | None = Field(
        default=None,
        description="Clip the upper tail so a handful of enormous trials do not flatten the "
        "distribution. Clipped trials are reported, not dropped.",
    )
    log_scale: bool = Field(
        default=False, description="Use logarithmic bin widths, for heavily skewed metrics."
    )


class KpiAnalysis(StrictModel):
    # A single headline number, for questions a chart would not improve

    kind: Literal["kpi"] = "kpi"
    measure: MeasureId = "trial_count"
    breakdown_dimension: DimensionId | None = Field(
        default=None,
        description="Optional dimension for supporting sub-figures beneath the headline number.",
    )
    breakdown_top_k: int = Field(default=5, ge=1, le=20)


AnalysisSpec = Annotated[
    GroupByAnalysis | NetworkAnalysis | ScatterAnalysis | HistogramAnalysis | KpiAnalysis,
    Field(discriminator="kind"),
]


class VisualizationRequest(StrictModel):
    # The chart the planner wants, and how to caption it

    type: VisualizationType
    title: str = Field(
        min_length=3,
        max_length=160,
        description="Human-readable title stating what is shown and for what population.",
    )
    subtitle: str | None = Field(
        default=None, max_length=240, description="Optional clarifying line beneath the title."
    )


class AnalysisPlan(StrictModel):
    # The complete, validated plan produced by the planner

    interpretation: str = Field(
        min_length=3,
        max_length=600,
        description="How the question was understood, in one or two plain sentences.",
    )
    assumptions: StringList = Field(
        default_factory=list,
        max_length=8,
        description="Choices made that the user did not specify and might disagree with — "
        "a date window, a synonym, a decision to count by MeSH term rather than raw name.",
    )
    retrieval: RetrievalSpec
    analysis: AnalysisSpec
    visualization: VisualizationRequest

    @property
    def dimension_ids(self) -> tuple[str, ...]:
        # Every dimension this analysis touches, to know which API fields to ask for
        analysis = self.analysis
        ids: list[str] = []
        if isinstance(analysis, GroupByAnalysis):
            ids = [analysis.dimension, *( [analysis.series_dimension] if analysis.series_dimension else [])]
        elif isinstance(analysis, NetworkAnalysis):
            ids = [analysis.source_dimension, analysis.target_dimension]
        elif isinstance(analysis, ScatterAnalysis):
            ids = [analysis.color_dimension] if analysis.color_dimension else []
        elif isinstance(analysis, KpiAnalysis):
            ids = [analysis.breakdown_dimension] if analysis.breakdown_dimension else []
        return tuple(dict.fromkeys(ids))

    @property
    def metric_ids(self) -> tuple[str, ...]:
        analysis = self.analysis
        if isinstance(analysis, ScatterAnalysis):
            return (analysis.x_metric, analysis.y_metric)
        if isinstance(analysis, HistogramAnalysis):
            return (analysis.metric,)
        return ()


__all__ = [
    "AnalysisPlan",
    "AnalysisSpec",
    "Cohort",
    "GroupByAnalysis",
    "HistogramAnalysis",
    "KpiAnalysis",
    "NetworkAnalysis",
    "RetrievalSpec",
    "ScatterAnalysis",
    "TrialFilterSpec",
    "VisualizationRequest",
    "VisualizationType",
    "TEMPORAL_DIMENSION_IDS",
]
