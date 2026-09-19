# What gets computed for each bucket and what the visualization axes use

# 2 registries: measures and metrics

# Measures: Aggregate functions applied to the trials in a bucket: used for the y-axis name of a bar or line chart. Describes many trials (could be median, mode, whatever the visualization needs)

# Metrics: Per-trial values: the axes of a scatter plot and the binned field of a histogram. Describes one trial, not a group

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.ctgov.normalize import TrialRecord, org_key


@dataclass(frozen=True)
class Measure:
    # Computes trials in one bucket

    id: str
    label: str
    unit: str
    compute: Callable[[Sequence[TrialRecord]], float | int | None]
    description: str
    requires_field: str | None = None
    # Trials missing values are excluded from this measure and counted in "meta.coverage.records_missing_measure" instead of being zero
    # Since for example, a trial that doesn't report enrollment is not a trial that didn't enroll anybody

    is_integer: bool = False


def _enrollments(records: Sequence[TrialRecord]) -> list[int]:
    return [r.enrollment for r in records if r.enrollment is not None]


def _trial_count(records: Sequence[TrialRecord]) -> int:
    return len(records)


def _total_enrollment(records: Sequence[TrialRecord]) -> int | None:
    values = _enrollments(records)
    return sum(values) if values else None


def _median_enrollment(records: Sequence[TrialRecord]) -> float | None:
    values = _enrollments(records)
    return round(statistics.median(values), 1) if values else None


def _mean_enrollment(records: Sequence[TrialRecord]) -> float | None:
    values = _enrollments(records)
    return round(statistics.fmean(values), 1) if values else None


def _distinct_sponsors(records: Sequence[TrialRecord]) -> int:
    return len({org_key(r.lead_sponsor) for r in records if r.lead_sponsor})


def _distinct_drugs(records: Sequence[TrialRecord]) -> int:
    return len({term.lower() for r in records for term in r.intervention_meshes})


_MEASURES: tuple[Measure, ...] = (
    Measure(
        id="trial_count",
        label="Number of Trials",
        unit="trials",
        compute=_trial_count,
        description="Count of distinct trials in the bucket. The default measure.",
        is_integer=True,
    ),
    Measure(
        id="total_enrollment",
        label="Total Enrollment",
        unit="participants",
        compute=_total_enrollment,
        description="Sum of reported participant counts. Mixes actual and estimated figures.",
        requires_field="enrollment",
        is_integer=True,
    ),
    Measure(
        id="median_enrollment",
        label="Median Enrollment",
        unit="participants",
        compute=_median_enrollment,
        description="Median participant count. Preferred over the mean, which a few very "
        "large trials will distort.",
        requires_field="enrollment",
    ),
    Measure(
        id="mean_enrollment",
        label="Mean Enrollment",
        unit="participants",
        compute=_mean_enrollment,
        description="Average participant count. Sensitive to outliers.",
        requires_field="enrollment",
    ),
    Measure(
        id="distinct_sponsor_count",
        label="Distinct Sponsors",
        unit="sponsors",
        compute=_distinct_sponsors,
        description="Number of distinct lead sponsors, after name normalization. Useful for "
        "questions about how crowded or concentrated a research area is.",
        is_integer=True,
    ),
    Measure(
        id="distinct_drug_count",
        label="Distinct Drugs",
        unit="drugs",
        compute=_distinct_drugs,
        description="Number of distinct MeSH intervention terms in the bucket.",
        is_integer=True,
    ),
)

MEASURES: dict[str, Measure] = {m.id: m for m in _MEASURES}
MEASURE_IDS: tuple[str, ...] = tuple(MEASURES)


def get_measure(measure_id: str) -> Measure:
    try:
        return MEASURES[measure_id]
    except KeyError:
        raise KeyError(
            f"Unknown measure {measure_id!r}. Valid measures: {', '.join(MEASURE_IDS)}"
        ) from None

# Per-trial fields 

@dataclass(frozen=True)
class Metric:
    # values describing a single trial

    id: str
    label: str
    unit: str
    source_field: str
    api_fields: tuple[str, ...]
    extract: Callable[[TrialRecord], float | None]
    description: str
    is_integer: bool = True


def _months_between(record: TrialRecord) -> float | None:
    # Planned duration in months, from start and end dates
    start, end = record.start_date, record.completion_date
    if start is None or end is None:
        return None
    start_months = start.year * 12 + ((start.month or 6) - 1)
    end_months = end.year * 12 + ((end.month or 6) - 1)
    duration = end_months - start_months
    return float(duration) if duration >= 0 else None


_METRICS: tuple[Metric, ...] = (
    Metric(
        id="enrollment",
        label="Enrollment",
        unit="participants",
        source_field="protocolSection.designModule.enrollmentInfo.count",
        api_fields=("EnrollmentCount", "EnrollmentType"),
        extract=lambda r: float(r.enrollment) if r.enrollment is not None else None,
        description="Reported participant count, actual or estimated.",
    ),
    Metric(
        id="start_year",
        label="Start Year",
        unit="year",
        source_field="protocolSection.statusModule.startDateStruct.date",
        api_fields=("StartDate",),
        extract=lambda r: float(r.start_date.year) if r.start_date else None,
        description="Year the trial started, as a number.",
    ),
    Metric(
        id="completion_year",
        label="Completion Year",
        unit="year",
        source_field="protocolSection.statusModule.completionDateStruct.date",
        api_fields=("CompletionDate",),
        extract=lambda r: float(r.completion_date.year) if r.completion_date else None,
        description="Year the trial completed or is due to complete.",
    ),
    Metric(
        id="duration_months",
        label="Planned Duration",
        unit="months",
        source_field="protocolSection.statusModule.(startDateStruct|completionDateStruct).date",
        api_fields=("StartDate", "CompletionDate"),
        extract=_months_between,
        description="Months from start to completion. Approximate when dates are year-only.",
    ),
    Metric(
        id="country_count",
        label="Number of Countries",
        unit="countries",
        source_field="protocolSection.contactsLocationsModule.locations.country",
        api_fields=("LocationCountry",),
        extract=lambda r: float(len(r.countries)) if r.countries else None,
        description="How many countries the trial runs sites in. A proxy for trial reach.",
    ),
    Metric(
        id="intervention_count",
        label="Number of Interventions",
        unit="interventions",
        source_field="protocolSection.armsInterventionsModule.interventions",
        api_fields=("InterventionName", "InterventionType"),
        extract=lambda r: float(len(r.interventions)) if r.interventions else None,
        description="How many interventions the trial lists. High values suggest combination "
        "or multi-arm studies.",
    ),
)

METRICS: dict[str, Metric] = {m.id: m for m in _METRICS}
METRIC_IDS: tuple[str, ...] = tuple(METRICS)


def get_metric(metric_id: str) -> Metric:
    try:
        return METRICS[metric_id]
    except KeyError:
        raise KeyError(
            f"Unknown metric {metric_id!r}. Valid metrics: {', '.join(METRIC_IDS)}"
        ) from None
