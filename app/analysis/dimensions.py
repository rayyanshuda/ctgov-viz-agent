# The dimension registry: every way this service knows how to group trials

# A dimension is the x-axis of a chart: group by phase, by country, by start year.

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ctgov.countries import iso3_for
from app.ctgov.enums import (
    ALLOCATIONS,
    INTERVENTION_TYPES,
    MASKINGS,
    PHASES,
    PRIMARY_PURPOSES,
    SEXES,
    SPONSOR_CLASSES,
    STANDARD_AGES,
    STATUSES,
    STUDY_TYPES,
    humanize,
)
from app.ctgov.normalize import TrialRecord, org_key

DimensionKind = Literal["nominal", "ordinal", "temporal", "quantitative"]

# A bucket for trials that never reported this field.
# Missing data gets its own bucket instead of being dropped, so a chart doesn't imply a smaller set of trials
UNKNOWN_KEY = "__unknown__"


@dataclass(frozen=True, slots=True)
class DimValue:
    # One bucket a trial falls into, with the evidence of why it is here

    key: str
    # Identifier used for grouping and sorting

    label: str
    # What gets printed on the axis or the node

    source_excerpt: str
    # The value from the API response that produced this bucket

    extra: dict[str, Any] = field(default_factory=dict)
    # Extra fields added to the row, like {"country_iso3": "USA"} for maps


@dataclass(frozen=True)
class Dimension:
    # One way of grouping trials

    id: str
    label: str
    kind: DimensionKind
    multi_valued: bool
    source_field: str
    api_fields: tuple[str, ...]
    extract: Callable[[TrialRecord], list[DimValue]]
    description: str
    enum_values: tuple[str, ...] | None = None
    essie_area: str | None = None
    category_order: tuple[str, ...] | None = None
    # Display order for dimensions with a natural order, e.g. Phase 1 before Phase 2

    network_eligible: bool = False

    @property
    def supports_exact_counts(self) -> bool:
        # True if the executor can count this dimension one value at a time
        return self.enum_values is not None and self.essie_area is not None


def _unknown(reason: str = "not reported") -> DimValue:
    return DimValue(key=UNKNOWN_KEY, label="Unknown", source_excerpt=f"({reason})")


def _build_enum(raw: Sequence[str]) -> list[DimValue]:
    # Turn raw enum values into labelled buckets that cite themselves
    return [DimValue(key=v, label=humanize(v), source_excerpt=v) for v in raw]


# Extractors

def _extract_phase(record: TrialRecord) -> list[DimValue]:
    # An interventional trial may register as spanning phases, e.g. ["PHASE1","PHASE2"].
    if not record.phases:
        return [_unknown("no phase registered")]
    return _build_enum(record.phases)


def _extract_single_enum(
    attr: str,
) -> Callable[[TrialRecord], list[DimValue]]:
    def _extract(record: TrialRecord) -> list[DimValue]:
        value = getattr(record, attr)
        if not value:
            return [_unknown()]
        return [DimValue(key=value, label=humanize(value), source_excerpt=value)]

    return _extract


def _extract_multi_enum(attr: str) -> Callable[[TrialRecord], list[DimValue]]:
    def _extract(record: TrialRecord) -> list[DimValue]:
        values = getattr(record, attr)
        if not values:
            return [_unknown()]
        return _build_enum(values)

    return _extract


def _extract_date_part(
    attr: str, granularity: Literal["year", "quarter", "month"]
) -> Callable[[TrialRecord], list[DimValue]]:
    # Put a date into a year, quarter, or month bucket.
    # A year-only date like "2016" cannot tell you the quarter or the month, so those
    # go to the unknown bucket instead of being assigned to Q1 or January.

    def _extract(record: TrialRecord) -> list[DimValue]:
        date = getattr(record, attr)
        if date is None:
            return [_unknown("no date reported")]
        if granularity == "year":
            return [DimValue(key=f"{date.year:04d}", label=str(date.year), source_excerpt=date.raw)]
        if date.month is None:
            return [_unknown("date reported to year precision only")]
        if granularity == "quarter":
            key = f"{date.year:04d}-Q{date.quarter}"
            return [DimValue(key=key, label=key, source_excerpt=date.raw)]
        key = f"{date.year:04d}-{date.month:02d}"
        return [DimValue(key=key, label=key, source_excerpt=date.raw)]

    return _extract


def _extract_lead_sponsor(record: TrialRecord) -> list[DimValue]:
    if not record.lead_sponsor:
        return [_unknown()]
    return [
        DimValue(
            key=org_key(record.lead_sponsor),
            label=record.lead_sponsor,
            source_excerpt=record.lead_sponsor,
        )
    ]


def _extract_collaborator(record: TrialRecord) -> list[DimValue]:
    if not record.collaborators:
        return [DimValue(key=UNKNOWN_KEY, label="No collaborators", source_excerpt="(none listed)")]
    return [DimValue(key=org_key(name), label=name, source_excerpt=name) for name in record.collaborators]


def _extract_country(record: TrialRecord) -> list[DimValue]:
    if not record.countries:
        return [_unknown("no study locations listed")]
    return [
        DimValue(
            key=name,
            label=name,
            source_excerpt=name,
            # Three dissolved states in the data have no ISO3 code; "None" is passed
            # through so a renderer can skip the shape but still show the bar.
            extra={"country_iso3": iso3_for(name)},
        )
        for name in record.countries
    ]


def _extract_intervention_type(record: TrialRecord) -> list[DimValue]:
    types = [i.type for i in record.interventions if i.type]
    if not types:
        return [_unknown()]
    seen: set[str] = set()
    out: list[DimValue] = []
    for t in types:
        if t not in seen:
            seen.add(t)
            out.append(DimValue(key=t, label=humanize(t), source_excerpt=t))
    return out


def _extract_intervention_name(record: TrialRecord) -> list[DimValue]:
    if not record.interventions:
        return [_unknown()]
    seen: set[str] = set()
    out: list[DimValue] = []
    for item in record.interventions:
        key = item.name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(DimValue(key=key, label=item.name, source_excerpt=item.name))
    return out


def _extract_mesh(attr: str, noun: str) -> Callable[[TrialRecord], list[DimValue]]:
    def _extract(record: TrialRecord) -> list[DimValue]:
        terms = getattr(record, attr)
        if not terms:
            return [_unknown(f"no {noun} MeSH terms assigned")]
        return [DimValue(key=t.lower(), label=t, source_excerpt=t) for t in terms]

    return _extract


def _extract_free_text(attr: str) -> Callable[[TrialRecord], list[DimValue]]:
    def _extract(record: TrialRecord) -> list[DimValue]:
        values = getattr(record, attr)
        if not values:
            return [_unknown()]
        return [DimValue(key=v.lower(), label=v, source_excerpt=v) for v in values]

    return _extract


ENROLLMENT_BINS: tuple[tuple[int, int | None, str], ...] = (
    (0, 0, "0"),
    (1, 9, "1-9"),
    (10, 49, "10-49"),
    (50, 99, "50-99"),
    (100, 499, "100-499"),
    (500, 999, "500-999"),
    (1_000, 4_999, "1,000-4,999"),
    (5_000, None, "5,000+"),
)


def _extract_enrollment_bucket(record: TrialRecord) -> list[DimValue]:
    if record.enrollment is None:
        return [_unknown("no enrollment reported")]
    count = record.enrollment
    for low, high, label in ENROLLMENT_BINS:
        if count >= low and (high is None or count <= high):
            return [DimValue(key=label, label=label, source_excerpt=str(count))]
    return [_unknown()]


def _extract_results_posted(record: TrialRecord) -> list[DimValue]:
    value = "Yes" if record.has_results else "No"
    return [DimValue(key=value, label=value, source_excerpt=str(record.has_results).lower())]


def _extract_cohort(record: TrialRecord) -> list[DimValue]:
    name = record.cohort or "All trials"
    return [DimValue(key=name, label=name, source_excerpt=name)]


# Registry

_DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        id="phase",
        label="Trial Phase",
        kind="ordinal",
        multi_valued=True,
        source_field="protocolSection.designModule.phases",
        api_fields=("Phase",),
        extract=_extract_phase,
        description="Clinical trial phase. Trials registered across two phases count in both.",
        enum_values=PHASES,
        essie_area="Phase",
        category_order=PHASES,
    ),
    Dimension(
        id="overall_status",
        label="Recruitment Status",
        kind="nominal",
        multi_valued=False,
        source_field="protocolSection.statusModule.overallStatus",
        api_fields=("OverallStatus",),
        extract=_extract_single_enum("overall_status"),
        description="Current recruitment status, e.g. Recruiting, Completed, Terminated.",
        enum_values=STATUSES,
        essie_area="OverallStatus",
    ),
    Dimension(
        id="study_type",
        label="Study Type",
        kind="nominal",
        multi_valued=False,
        source_field="protocolSection.designModule.studyType",
        api_fields=("StudyType",),
        extract=_extract_single_enum("study_type"),
        description="Interventional, Observational or Expanded Access.",
        enum_values=STUDY_TYPES,
        essie_area="StudyType",
    ),
    Dimension(
        id="start_year",
        label="Start Year",
        kind="temporal",
        multi_valued=False,
        source_field="protocolSection.statusModule.startDateStruct.date",
        api_fields=("StartDate",),
        extract=_extract_date_part("start_date", "year"),
        description="Calendar year the trial started. The default axis for trend questions.",
    ),
    Dimension(
        id="start_quarter",
        label="Start Quarter",
        kind="temporal",
        multi_valued=False,
        source_field="protocolSection.statusModule.startDateStruct.date",
        api_fields=("StartDate",),
        extract=_extract_date_part("start_date", "quarter"),
        description="Calendar quarter the trial started. Year-only dates fall in Unknown.",
    ),
    Dimension(
        id="start_month",
        label="Start Month",
        kind="temporal",
        multi_valued=False,
        source_field="protocolSection.statusModule.startDateStruct.date",
        api_fields=("StartDate",),
        extract=_extract_date_part("start_date", "month"),
        description="Calendar month the trial started. Year-only dates fall in Unknown.",
    ),
    Dimension(
        id="completion_year",
        label="Completion Year",
        kind="temporal",
        multi_valued=False,
        source_field="protocolSection.statusModule.completionDateStruct.date",
        api_fields=("CompletionDate",),
        extract=_extract_date_part("completion_date", "year"),
        description="Calendar year the trial completed or is due to complete.",
    ),
    Dimension(
        id="lead_sponsor",
        network_eligible=True,
        label="Lead Sponsor",
        kind="nominal",
        multi_valued=False,
        source_field="protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
        api_fields=("LeadSponsorName",),
        extract=_extract_lead_sponsor,
        description="Organization running the trial. Legal suffixes are normalized so name "
        "variants of one sponsor merge.",
    ),
    Dimension(
        id="sponsor_class",
        label="Sponsor Type",
        kind="nominal",
        multi_valued=False,
        source_field="protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
        api_fields=("LeadSponsorClass",),
        extract=_extract_single_enum("lead_sponsor_class"),
        description="Sponsor category: Industry, NIH, Federal, Other Government, Network, Other.",
        enum_values=SPONSOR_CLASSES,
        essie_area="LeadSponsorClass",
    ),
    Dimension(
        id="collaborator",
        network_eligible=True,
        label="Collaborator",
        kind="nominal",
        multi_valued=True,
        source_field="protocolSection.sponsorCollaboratorsModule.collaborators.name",
        api_fields=("CollaboratorName",),
        extract=_extract_collaborator,
        description="Collaborating organizations. Useful as a network endpoint.",
    ),
    Dimension(
        id="country",
        network_eligible=True,
        label="Country",
        kind="nominal",
        multi_valued=True,
        source_field="protocolSection.contactsLocationsModule.locations.country",
        api_fields=("LocationCountry",),
        extract=_extract_country,
        description="Countries with at least one study site. Multi-country trials count once "
        "per country. Rows carry an ISO3 code for choropleths.",
        essie_area="LocationCountry",
    ),
    Dimension(
        id="intervention_type",
        network_eligible=True,
        label="Intervention Type",
        kind="nominal",
        multi_valued=True,
        source_field="protocolSection.armsInterventionsModule.interventions.type",
        api_fields=("InterventionType", "InterventionName"),
        extract=_extract_intervention_type,
        description="Kind of intervention: Drug, Biological, Device, Behavioral, Procedure, etc.",
        enum_values=INTERVENTION_TYPES,
        essie_area="InterventionType",
    ),
    Dimension(
        id="intervention_name",
        network_eligible=True,
        label="Intervention (as registered)",
        kind="nominal",
        multi_valued=True,
        source_field="protocolSection.armsInterventionsModule.interventions.name",
        api_fields=("InterventionName", "InterventionType"),
        extract=_extract_intervention_name,
        description="Raw intervention names as sponsors wrote them. Verbatim but messy "
        "('Nivolumab + Relatlimab'); prefer intervention_mesh for drug analysis.",
    ),
    Dimension(
        id="intervention_mesh",
        network_eligible=True,
        label="Drug / Intervention (MeSH)",
        kind="nominal",
        multi_valued=True,
        source_field="derivedSection.interventionBrowseModule.meshes.term",
        api_fields=("InterventionMeshTerm",),
        extract=_extract_mesh("intervention_meshes", "intervention"),
        description="NLM-normalized intervention terms. The right choice for drug networks and "
        "drug co-occurrence, since it resolves brand and combination names.",
    ),
    Dimension(
        id="condition",
        network_eligible=True,
        label="Condition (as registered)",
        kind="nominal",
        multi_valued=True,
        source_field="protocolSection.conditionsModule.conditions",
        api_fields=("Condition",),
        extract=_extract_free_text("conditions"),
        description="Raw condition names as sponsors wrote them.",
    ),
    Dimension(
        id="condition_mesh",
        network_eligible=True,
        label="Condition (MeSH)",
        kind="nominal",
        multi_valued=True,
        source_field="derivedSection.conditionBrowseModule.meshes.term",
        api_fields=("ConditionMeshTerm",),
        extract=_extract_mesh("condition_meshes", "condition"),
        description="NLM-normalized condition terms, deduplicated across spelling variants.",
    ),
    Dimension(
        id="primary_purpose",
        label="Primary Purpose",
        kind="nominal",
        multi_valued=False,
        source_field="protocolSection.designModule.designInfo.primaryPurpose",
        api_fields=("DesignPrimaryPurpose",),
        extract=_extract_single_enum("primary_purpose"),
        description="Treatment, Prevention, Diagnostic, Supportive Care, Basic Science, etc.",
        enum_values=PRIMARY_PURPOSES,
        essie_area="DesignPrimaryPurpose",
    ),
    Dimension(
        id="allocation",
        label="Allocation",
        kind="nominal",
        multi_valued=False,
        source_field="protocolSection.designModule.designInfo.allocation",
        api_fields=("DesignAllocation",),
        extract=_extract_single_enum("allocation"),
        description="Randomized, Non-randomized or Not Applicable.",
        enum_values=ALLOCATIONS,
        essie_area="DesignAllocation",
    ),
    Dimension(
        id="masking",
        label="Masking",
        kind="nominal",
        multi_valued=False,
        source_field="protocolSection.designModule.designInfo.maskingInfo.masking",
        api_fields=("DesignMasking",),
        extract=_extract_single_enum("masking"),
        description="Blinding level: None (open label) through Quadruple.",
        enum_values=MASKINGS,
        essie_area="DesignMasking",
    ),
    Dimension(
        id="sex",
        label="Eligible Sex",
        kind="nominal",
        multi_valued=False,
        source_field="protocolSection.eligibilityModule.sex",
        api_fields=("Sex",),
        extract=_extract_single_enum("sex"),
        description="Sex eligible for enrollment: All, Female or Male.",
        enum_values=SEXES,
        essie_area="Sex",
    ),
    Dimension(
        id="age_group",
        label="Age Group",
        kind="nominal",
        multi_valued=True,
        source_field="protocolSection.eligibilityModule.stdAges",
        api_fields=("StdAge",),
        extract=_extract_multi_enum("std_ages"),
        description="Standard age brackets: Child, Adult, Older Adult. Trials span several.",
        enum_values=STANDARD_AGES,
        essie_area="StdAge",
    ),
    Dimension(
        id="enrollment_bucket",
        label="Enrollment Size",
        kind="ordinal",
        multi_valued=False,
        source_field="protocolSection.designModule.enrollmentInfo.count",
        api_fields=("EnrollmentCount", "EnrollmentType"),
        extract=_extract_enrollment_bucket,
        description="Participant count grouped into size bands. Mixes actual and estimated "
        "enrollment, since the API reports both.",
        category_order=tuple(label for _, _, label in ENROLLMENT_BINS),
    ),
    Dimension(
        id="results_posted",
        label="Results Posted",
        kind="nominal",
        multi_valued=False,
        source_field="hasResults",
        api_fields=("HasResults",),
        extract=_extract_results_posted,
        description="Whether summary results have been posted to ClinicalTrials.gov.",
        category_order=("Yes", "No"),
    ),
    Dimension(
        id="cohort",
        label="Comparison Group",
        kind="nominal",
        multi_valued=False,
        source_field="__cohort__",
        api_fields=(),
        extract=_extract_cohort,
        description="Which named cohort a trial was retrieved for. Derived from the query, not "
        "from the API — this is what makes 'A vs B' comparisons work. Use as series_dimension.",
    ),
)

DIMENSIONS: dict[str, Dimension] = {d.id: d for d in _DIMENSIONS}
DIMENSION_IDS: tuple[str, ...] = tuple(DIMENSIONS)

TEMPORAL_DIMENSION_IDS: tuple[str, ...] = tuple(
    d.id for d in _DIMENSIONS if d.kind == "temporal"
)


def get_dimension(dimension_id: str) -> Dimension:
    # Look up a dimension. The error lists the valid options, which is what gets sent
    # back to the model when it picks a dimension that doesn't exist.
    try:
        return DIMENSIONS[dimension_id]
    except KeyError:
        raise KeyError(
            f"Unknown dimension {dimension_id!r}. Valid dimensions: {', '.join(DIMENSION_IDS)}"
        ) from None


def required_api_fields(dimension_ids: Sequence[str]) -> tuple[str, ...]:
    # Which API fields to request for these dimensions.
    # Only asking for the fields a plan needs
    fields: set[str] = set()
    for dimension_id in dimension_ids:
        fields.update(DIMENSIONS[dimension_id].api_fields)
    return tuple(sorted(fields))
