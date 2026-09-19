# Generic group engine

# Every bar, line, map, and table in this service comes from the function in this file "aggregate".
# It takes records, including a dimension, a measure, and optionally a series dimension, and returns
# buckets. It is not given the drug name, phase, or sponsor, because that data lives in the dimension registry
# It is designed that way to stop new questions from needing their own code path.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.analysis.dimensions import UNKNOWN_KEY, Dimension, DimValue
from app.analysis.measures import Measure
from app.ctgov.normalize import TrialRecord


@dataclass(frozen=True, slots=True)
class Contribution:
    # A trial's contribution to a bucket, and a sentence for it

    record: TrialRecord
    excerpt: str


@dataclass
class Bucket:
    # One aggregated data point

    key: str
    label: str
    value: float | int | None
    contributions: list[Contribution] = field(default_factory=list)
    series_key: str | None = None
    series_label: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    share_pct: float | None = None

    total_trials: int | None = None

    @property
    def trial_count(self) -> int:
        # Trials in this bucket, the true total when it is known, otherwise what it currently holds
        return self.total_trials if self.total_trials is not None else len(self.contributions)


@dataclass
class AggregationResult:
    # Buckets, including everything the response needs to describe how they were made.

    buckets: list[Bucket]
    dimension: Dimension
    measure: Measure
    series_dimension: Dimension | None = None
    total_records: int = 0
    records_missing_dimension: int = 0
    records_missing_measure: int = 0
    categories_omitted: int = 0
    # Buckets dropped by ``top_k`` or ``min_value``, so the caller can say "showing top 15 of 212"

    @property
    def is_multi_valued(self) -> bool:
        return self.dimension.multi_valued or bool(
            self.series_dimension and self.series_dimension.multi_valued
        )

    @property
    def counting_semantics(self) -> str:
        # explaining what ""one unit" in this chart means
        exploding = [
            d.label.lower()
            for d in (self.dimension, self.series_dimension)
            if d is not None and d.multi_valued
        ]
        if not exploding:
            return (
                "Each trial is counted exactly once; bucket values partition the "
                f"{self.total_records:,} analyzed trials."
            )
        joined = " and ".join(exploding)
        return (
            f"A trial may report several values for {joined}, so it is counted once per "
            "value. Bucket values therefore sum to more than the number of trials."
        )


def _category_sort_key(dimension: Dimension, key: str, label: str) -> tuple[int, Any]:
    # Natural ordering for a dimension's categories, with Unknown always last
    if key == UNKNOWN_KEY:
        return (2, "")
    if dimension.category_order:
        try:
            return (0, dimension.category_order.index(key))
        except ValueError:
            return (1, label.lower())
    if dimension.kind == "temporal":
        # Keys are zero-padded ("2016", "2016-Q2", "2016-04"), so lexicographic
        # ordering is chronological.
        return (0, key)
    return (0, label.lower())


def _temporal_sequence(keys: Sequence[str]) -> list[str]:
    # every period between the earliest and latest date key. 
    # any gaps become zeros

    # handles the key shapes the registry produces: "2016", "2016-Q2" and "2016-04"
    # returns the input unchanged if the shapes are unrecognized

    real = sorted(k for k in keys if k != UNKNOWN_KEY)
    if len(real) < 2:
        return list(real)

    first = real[0]
    if all(len(k) == 4 and k.isdigit() for k in real):
        return [str(y) for y in range(int(first), int(real[-1]) + 1)]

    if all(len(k) == 7 and k[4] == "-" and k[5] == "Q" for k in real):
        start_y, start_q = int(first[:4]), int(first[6])
        end_y, end_q = int(real[-1][:4]), int(real[-1][6])
        out = []
        y, q = start_y, start_q
        while (y, q) <= (end_y, end_q):
            out.append(f"{y:04d}-Q{q}")
            q += 1
            if q > 4:
                y, q = y + 1, 1
        return out

    if all(len(k) == 7 and k[4] == "-" and k[5:].isdigit() for k in real):
        start_y, start_m = int(first[:4]), int(first[5:])
        end_y, end_m = int(real[-1][:4]), int(real[-1][5:])
        out = []
        y, m = start_y, start_m
        while (y, m) <= (end_y, end_m):
            out.append(f"{y:04d}-{m:02d}")
            m += 1
            if m > 12:
                y, m = y + 1, 1
        return out

    return real


_MAX_FILLED_CELLS = 5000
#Ceiling on generated (category, series) pairs, so a high-cardinality pairing cannot produce many consecutive empty rows


def aggregate(
    records: Sequence[TrialRecord],
    *,
    dimension: Dimension,
    measure: Measure,
    series_dimension: Dimension | None = None,
    top_k: int | None = None,
    sort_by: Literal["value", "category"] = "value",
    sort_order: Literal["asc", "desc"] = "desc",
    include_unknown: bool = False,
    min_value: float | None = None,
    fill_gaps: bool = True,
) -> AggregationResult:
    # Group "records" and compute "measure" for each bucket.
    grouped: dict[tuple[str, str | None], list[Contribution]] = {}
    labels: dict[str, tuple[str, dict[str, Any]]] = {}
    series_labels: dict[str, str] = {}
    missing_dimension = 0

    for record in records:
        values = dimension.extract(record)
        if any(v.key == UNKNOWN_KEY for v in values):
            missing_dimension += 1

        series_values: list[DimValue | None]
        series_values = list(series_dimension.extract(record)) if series_dimension else [None]

        for value in values:
            labels.setdefault(value.key, (value.label, value.extra))
            for series_value in series_values:
                series_key = series_value.key if series_value else None
                if series_value is not None:
                    series_labels.setdefault(series_value.key, series_value.label)
                grouped.setdefault((value.key, series_key), []).append(
                    Contribution(record=record, excerpt=value.source_excerpt)
                )

    if not include_unknown:
        grouped = {k: v for k, v in grouped.items() if k[0] != UNKNOWN_KEY}

    # Fill absent combinations so grouped and time-series charts are rectangular.
    category_keys = {key for key, _ in grouped}
    if fill_gaps and dimension.kind == "temporal":
        category_keys.update(_temporal_sequence([k for k in category_keys if k != UNKNOWN_KEY]))
    series_keys: list[str | None] = (
        sorted(series_labels) if series_dimension else [None]  # type: ignore[assignment]
    )
    if fill_gaps and len(category_keys) * len(series_keys) <= _MAX_FILLED_CELLS:
        for category in category_keys:
            for series in series_keys:
                grouped.setdefault((category, series), [])

    missing_measure = 0
    if measure.requires_field is not None:
        missing_measure = sum(
            1 for r in records if getattr(r, measure.requires_field, None) is None
        )

    buckets: list[Bucket] = []
    for (key, series_key), contributions in grouped.items():
        label, extra = labels.get(key, (key, {}))
        buckets.append(
            Bucket(
                key=key,
                label="Unknown" if key == UNKNOWN_KEY else label,
                value=measure.compute([c.record for c in contributions]),
                contributions=contributions,
                series_key=series_key,
                series_label=series_labels.get(series_key) if series_key else None,
                extra=dict(extra),
            )
        )

    # Rank categories on their combined value so that, in a multi-series chart, top_k
    # selects categories instead of randomly truncating one series.
    totals: dict[str, float] = {}
    for bucket in buckets:
        totals[bucket.key] = totals.get(bucket.key, 0.0) + float(bucket.value or 0)

    if min_value is not None:
        kept = {k for k, total in totals.items() if total >= min_value}
    else:
        kept = set(totals)

    # The Unknown bucket is a data-quality residual, not a category on the scale, so it
    # is ordered separately and always placed last; reversing the sort should not drag
    # "not reported" to the front of the chart.
    has_unknown = UNKNOWN_KEY in kept
    kept.discard(UNKNOWN_KEY)

    ordered_categories = sorted(
        kept,
        key=(
            (lambda k: (-totals[k], k))
            if sort_by == "value"
            else (lambda k: _category_sort_key(dimension, k, labels.get(k, (k, {}))[0]))
        ),
    )
    if (sort_by == "value" and sort_order == "asc") or (
        sort_by == "category" and sort_order == "desc"
    ):
        ordered_categories.reverse()
    if has_unknown:
        ordered_categories.append(UNKNOWN_KEY)

    categories_omitted = len(totals) - len(ordered_categories)
    if top_k is not None and len(ordered_categories) > top_k:
        # top_k is a ranking cut, so take the highest-valued categories regardless of the
        # display order the caller asked for, then restore that order.
        by_value = sorted(ordered_categories, key=lambda k: -totals[k])[:top_k]
        keep = set(by_value)
        categories_omitted += len(ordered_categories) - len(keep)
        ordered_categories = [k for k in ordered_categories if k in keep]

    position = {key: index for index, key in enumerate(ordered_categories)}
    buckets = [b for b in buckets if b.key in position]
    buckets.sort(key=lambda b: (position[b.key], b.series_label or ""))

    grand_total = sum(float(b.value or 0) for b in buckets)
    if grand_total > 0 and measure.id in {"trial_count", "total_enrollment"}:
        for bucket in buckets:
            bucket.share_pct = round(float(bucket.value or 0) / grand_total * 100, 2)

    return AggregationResult(
        buckets=buckets,
        dimension=dimension,
        measure=measure,
        series_dimension=series_dimension,
        total_records=len(records),
        records_missing_dimension=missing_dimension,
        records_missing_measure=missing_measure,
        categories_omitted=max(categories_omitted, 0),
    )
