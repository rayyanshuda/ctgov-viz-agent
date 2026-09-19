# The request schema

# Structured fields sit at the top level, matching the shape the assignment showed:
# {"query": ..., "drug_name": "Pembrolizumab"}. They are all optional, so an empty query
# is a complete request.

# Anything set here is a hard constraint that beats whatever the planner infers from the question

# A single value works anywhere a list is expected, so "drug_name": "aspirin" is the same
# as ["aspirin"]

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.models.plan import (
    InterventionTypeEnum,
    Phase,
    SponsorClass,
    Status,
    StudyType,
    VisualizationType,
)


def _as_list(value: Any) -> Any:
    # Accept a single string where a list was expected
    if value is None:
        return value
    if isinstance(value, str):
        return [value] if value.strip() else []
    return value


StrList = Annotated[list[str], BeforeValidator(_as_list)]
PhaseList = Annotated[list[Phase], BeforeValidator(_as_list)]
StatusList = Annotated[list[Status], BeforeValidator(_as_list)]
StudyTypeList = Annotated[list[StudyType], BeforeValidator(_as_list)]
InterventionTypeList = Annotated[list[InterventionTypeEnum], BeforeValidator(_as_list)]
SponsorClassList = Annotated[list[SponsorClass], BeforeValidator(_as_list)]


class RequestOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_studies: int | None = Field(
        default=None,
        ge=1,
        le=20_000,
        description="Cap on trials fetched per cohort. Higher is more accurate and slower. "
        "Defaults to the server setting (5,000).",
    )
    include_citations: bool = Field(
        default=True, description="Attach source trial references to each data point."
    )
    citations_per_datum: int = Field(
        default=3,
        ge=0,
        le=25,
        description="How many supporting trials to cite per bar, bucket, node or edge.",
    )
    include_plan: bool = Field(
        default=True,
        description="Return the validated analysis plan alongside the visualization.",
    )
    preferred_visualization: VisualizationType | None = Field(
        default=None,
        description="Hint the planner toward a chart type. Ignored if incompatible with the "
        "analysis, with a note in meta.warnings.",
    )


class VisualizeRequest(BaseModel):
    # A natural-language question, optionally narrowed by structured filters

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "query": "How has the number of trials for this drug changed over time?",
                    "drug_name": "Pembrolizumab",
                    "start_year": 2015,
                },
                {
                    "query": "Show a network of sponsors and drugs for multiple myeloma trials",
                },
            ]
        },
    )

    query: str = Field(
        min_length=3,
        max_length=500,
        description="The question to answer, in plain language.",
    )

    drug_name: StrList = Field(
        default_factory=list, description="Drug or intervention names to restrict to."
    )
    condition: StrList = Field(
        default_factory=list, description="Conditions or diseases to restrict to."
    )
    sponsor: StrList = Field(default_factory=list, description="Sponsor names to restrict to.")
    country: StrList = Field(
        default_factory=list,
        description="Countries to restrict to, spelled as ClinicalTrials.gov does "
        "(e.g. 'United States', 'South Korea').",
    )

    trial_phase: PhaseList = Field(default_factory=list, description="Phases to restrict to.")
    status: StatusList = Field(
        default_factory=list, description="Recruitment statuses to restrict to."
    )
    study_type: StudyTypeList = Field(
        default_factory=list, description="Study types to restrict to."
    )
    intervention_type: InterventionTypeList = Field(
        default_factory=list, description="Intervention types to restrict to."
    )
    sponsor_class: SponsorClassList = Field(
        default_factory=list, description="Sponsor categories to restrict to."
    )

    start_year: int | None = Field(
        default=None, ge=1900, le=2100, description="Earliest trial start year, inclusive."
    )
    end_year: int | None = Field(
        default=None, ge=1900, le=2100, description="Latest trial start year, inclusive."
    )

    options: RequestOptions = Field(default_factory=RequestOptions)

    @model_validator(mode="after")
    def _check_years(self) -> VisualizeRequest:
        if self.start_year is not None and self.end_year is not None:
            if self.start_year > self.end_year:
                raise ValueError("start_year must not be greater than end_year")
        return self

    def structured_filters(self) -> dict[str, Any]:
        # The filters the caller actually set, skipping anything left blank.
        # Used both to constrain the planner and to fill meta.filters_applied.user.
        supplied: dict[str, Any] = {}
        for name in (
            "drug_name",
            "condition",
            "sponsor",
            "country",
            "trial_phase",
            "status",
            "study_type",
            "intervention_type",
            "sponsor_class",
        ):
            value = getattr(self, name)
            if value:
                supplied[name] = value
        if self.start_year is not None:
            supplied["start_year"] = self.start_year
        if self.end_year is not None:
            supplied["end_year"] = self.end_year
        return supplied

    @property
    def has_structured_filters(self) -> bool:
        return bool(self.structured_filters())
