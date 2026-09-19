# The response schema, which is the contract a frontend renders against

# Built around one rule: a renderer should never have to guess. In practice that means:
# encoding names the row keys to read for each channel, so a renderer looks up which key
# holds the x value instead of hardcoding a name per chart type.
# Every row is a flat dict keyed by dimension and measure ids, the same shape the
# assignment used: {"phase": "Phase 3", "trial_count": 41}.
# Anything ambiguous about the numbers goes in meta: what one unit means, how much of the
# matching data was analyzed, what was left out, what was assumed.

# Charts carry data. Network graphs carry nodes and edges instead. Both keys always
# exist, so a client can just check which one is filled in.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.plan import AnalysisPlan, VisualizationType

ChannelType = Literal["nominal", "ordinal", "quantitative", "temporal", "geo"]


class Channel(BaseModel):
    """One visual channel: which row key to read, and how to treat it."""

    field: str = Field(description="Key to read from each row in `data`.")
    type: ChannelType = Field(description="Scale type the renderer should use.")
    title: str = Field(description="Axis or legend label.")
    unit: str | None = Field(default=None, description="Unit of measurement, if any.")


class NodeChannels(BaseModel):
    # Which keys to read from each entry in "nodes"

    id: str = "id"
    label: str = "label"
    group: str = "group"
    size: str = "degree"
    title: str = Field(default="Entity", description="What the nodes represent.")


class EdgeChannels(BaseModel):
    # Which keys to read from each entry in "edges"

    source: str = "source"
    target: str = "target"
    weight: str = "weight"
    title: str = Field(default="Co-occurrence", description="What the edges represent.")


class Encoding(BaseModel):
    # Field-to-channel mapping. Only the channels a chart type uses are populated

    model_config = ConfigDict(extra="forbid")

    x: Channel | None = None
    y: Channel | None = None
    series: Channel | None = Field(
        default=None, description="Present when the chart has multiple series."
    )
    color: Channel | None = None
    size: Channel | None = None
    location: Channel | None = Field(
        default=None, description="Geographic key for choropleths; `field` holds an ISO3 code."
    )
    node: NodeChannels | None = None
    edge: EdgeChannels | None = None


class Citation(BaseModel):
    # A pointer from one datum back to a trial record

    nct_id: str
    field: str = Field(description="Dotted path of the API field this value came from.")
    excerpt: str = Field(
        description="Verbatim value found at that field — never model-generated text."
    )
    context: str = Field(description="The trial's brief title, quoted verbatim for orientation.")
    url: str


class CitationIndexEntry(BaseModel):
    # Trial metadata, held once at the top level

    title: str
    url: str


class Visualization(BaseModel):
    # the rendering specification

    type: VisualizationType
    title: str
    subtitle: str | None = None
    encoding: Encoding
    data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Rows for chart types. Keys match the fields named in `encoding`. "
        "Each row may carry `citations` and `contributing_trial_count`.",
    )
    nodes: list[dict[str, Any]] | None = Field(
        default=None, description="Populated for network_graph only."
    )
    edges: list[dict[str, Any]] | None = Field(
        default=None, description="Populated for network_graph only."
    )


class CohortCoverage(BaseModel):
    # Retrieval outcome for one cohort

    name: str
    total_matching: int = Field(description="Studies matching this cohort's filters.")
    analyzed: int = Field(description="Studies actually retrieved and aggregated.")
    truncated: bool = Field(description="True when the cap stopped retrieval early.")


class Coverage(BaseModel):
    # How much of the matching data stands behind these numbers

    strategy: Literal["fetch_and_aggregate", "exact_counts"] = Field(
        description="`fetch_and_aggregate` downloads and groups records. `exact_counts` asks "
        "the API for a count per bucket, giving exact totals over result sets too large "
        "to download."
    )
    total_matching: int
    analyzed: int
    truncated: bool
    per_cohort: list[CohortCoverage] = Field(default_factory=list)
    records_missing_dimension: int = Field(
        default=0,
        description="Trials that did not report the grouping field. Shown as an Unknown "
        "bucket when `include_unknown` is set, otherwise excluded — but always counted here.",
    )
    records_missing_measure: int = Field(
        default=0, description="Trials lacking the field the measure needs."
    )
    categories_omitted: int = Field(
        default=0, description="Buckets dropped by top-k or a minimum-value threshold."
    )


class MeasureInfo(BaseModel):
    id: str
    label: str
    unit: str


class FiltersApplied(BaseModel):
    user: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured fields from the request. These override inferred values.",
    )
    inferred: dict[str, Any] = Field(
        default_factory=dict,
        description="Constraints the planner derived from the natural-language question.",
    )


class SourceInfo(BaseModel):
    name: str = "ClinicalTrials.gov"
    api: str = "https://clinicaltrials.gov/data-api/api"
    api_version: str = "v2"
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResponseMeta(BaseModel):
    # Everything needed to interpret the visualization

    interpretation: str = Field(description="How the question was understood.")
    assumptions: list[str] = Field(
        default_factory=list,
        description="Choices the user did not specify and might want to change.",
    )
    filters_applied: FiltersApplied
    counting_semantics: str = Field(
        description="What one unit in the chart means, including whether a trial can be "
        "counted in more than one bucket."
    )
    coverage: Coverage
    measure: MeasureInfo | None = None
    sort: dict[str, str] | None = Field(
        default=None, description="How rows are ordered, e.g. {'by': 'value', 'order': 'desc'}."
    )
    time_granularity: Literal["year", "quarter", "month"] | None = None
    ctgov_requests: list[dict[str, str]] = Field(
        default_factory=list,
        description="Exact query parameters sent to ClinicalTrials.gov. Replaying these "
        "against the public API reproduces the underlying data.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Anything that should qualify how the chart is read: truncation, "
        "pruning, fallbacks, sparse data.",
    )
    source: SourceInfo = Field(default_factory=SourceInfo)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VisualizeResponse(BaseModel):
    # The complete answer to one question

    status: Literal["ok", "no_data"] = Field(
        description="`no_data` means the query was understood and executed but matched no "
        "trials. The visualization is omitted rather than fabricated."
    )
    question: str = Field(description="The original question, echoed back.")
    visualization: Visualization | None = None
    meta: ResponseMeta
    plan: AnalysisPlan | None = Field(
        default=None, description="The validated plan that produced this result."
    )
    citation_index: dict[str, CitationIndexEntry] = Field(
        default_factory=dict,
        description="NCT ID to trial title and URL, for every trial cited anywhere in the "
        "response.",
    )


class ErrorResponse(BaseModel):
    # Problem details for a failed request

    error: str = Field(description="Machine-readable code, e.g. `upstream_error`.")
    message: str
    remedy: str | None = Field(default=None, description="What the caller can do about it.")
    details: dict[str, Any] | None = None


class CapabilitiesResponse(BaseModel):
    # self-describing, so a client can discover what is supported

    visualization_types: list[dict[str, Any]]
    dimensions: list[dict[str, Any]]
    measures: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    filters: dict[str, list[str]]
