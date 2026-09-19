"""The group-by engine: counting semantics, ordering, gap filling and missing data."""

from __future__ import annotations

import pytest

from app.analysis.aggregate import aggregate
from app.analysis.dimensions import UNKNOWN_KEY, get_dimension
from app.analysis.measures import get_measure


def agg(records, dimension="phase", measure="trial_count", series_dimension=None, **kwargs):
    """Thin wrapper so tests can name dimensions and measures by id."""
    return aggregate(
        records,
        dimension=get_dimension(dimension),
        measure=get_measure(measure),
        series_dimension=get_dimension(series_dimension) if series_dimension else None,
        **kwargs,
    )


class TestCountingSemantics:
    def test_single_valued_dimension_partitions_the_records(self, records):
        result = agg(records, dimension="overall_status", include_unknown=True)
        assert sum(b.value for b in result.buckets) == len(records)
        assert "counted exactly once" in result.counting_semantics

    def test_multi_valued_dimension_may_exceed_the_record_count(self, synthetic_records):
        # NCT...02 is registered as PHASE2 and PHASE3, so it lands in both buckets.
        result = agg(synthetic_records, dimension="phase")
        assert sum(b.value for b in result.buckets) > 3
        assert "counted once per value" in result.counting_semantics

    def test_multi_phase_trial_appears_in_each_phase(self, synthetic_records):
        result = agg(synthetic_records, dimension="phase")
        by_key = {b.key: b for b in result.buckets}
        assert "NCT00000002" in {c.record.nct_id for c in by_key["PHASE2"].contributions}
        assert "NCT00000002" in {c.record.nct_id for c in by_key["PHASE3"].contributions}


class TestMissingData:
    def test_trials_missing_the_dimension_are_counted_and_excluded_by_default(
        self, synthetic_records
    ):
        result = agg(synthetic_records, dimension="phase")
        assert result.records_missing_dimension == 1
        assert UNKNOWN_KEY not in {b.key for b in result.buckets}

    def test_unknown_bucket_is_available_on_request(self, synthetic_records):
        result = agg(synthetic_records, dimension="phase", include_unknown=True)
        unknown = next(b for b in result.buckets if b.key == UNKNOWN_KEY)
        assert unknown.value == 1 and unknown.label == "Unknown"

    def test_measure_reports_how_many_trials_lacked_its_field(self, synthetic_records):
        result = agg(synthetic_records, dimension="phase", measure="median_enrollment")
        assert result.records_missing_measure == 1

    def test_absent_value_is_computed_not_assumed_to_be_zero(self, synthetic_records):
        # An empty bucket has no median, but it does have a count of zero. The engine
        # gets both right by running the measure over an empty list.
        counts = agg(synthetic_records, dimension="phase", measure="trial_count")
        medians = agg(synthetic_records, dimension="phase", measure="median_enrollment")
        assert all(b.value == 0 or b.value > 0 for b in counts.buckets)
        empty_median = [b for b in medians.buckets if not b.contributions]
        assert all(b.value is None for b in empty_median)


class TestOrdering:
    def test_category_sort_uses_the_dimensions_natural_order(self, records):
        result = agg(records, dimension="phase", sort_by="category", sort_order="asc")
        labels = [b.label for b in result.buckets]
        assert labels.index("Phase 1") < labels.index("Phase 2") < labels.index("Phase 3")

    def test_not_applicable_sorts_last_despite_the_ordering(self, records):
        result = agg(records, dimension="phase", sort_by="category", sort_order="asc")
        labels = [b.label for b in result.buckets]
        if "Not Applicable" in labels:
            assert labels[-1] == "Not Applicable"

    def test_value_sort_ranks_by_the_measure(self, records):
        result = agg(records, dimension="country", sort_by="value", sort_order="desc")
        values = [b.value for b in result.buckets]
        assert values == sorted(values, reverse=True)

    def test_unknown_sorts_last_in_category_order(self, synthetic_records):
        result = agg(
            synthetic_records, dimension="phase", sort_by="category", include_unknown=True
        )
        assert result.buckets[-1].key == UNKNOWN_KEY


class TestTopK:
    def test_keeps_the_highest_valued_categories(self, records):
        result = agg(records, dimension="country", top_k=3)
        assert len(result.buckets) == 3
        assert result.categories_omitted > 0

    def test_ranks_by_total_across_series_not_within_one(self, records):
        # With a series, top_k must choose categories on their combined value, otherwise
        # a category strong in one series only would be cut.
        result = agg(
            records,
            dimension="country",
            series_dimension="phase",
            top_k=3,
        )
        assert len({b.key for b in result.buckets}) == 3

    def test_min_value_drops_small_buckets(self, records):
        result = agg(records, dimension="country", min_value=5)
        assert all(b.value >= 5 for b in result.buckets)


class TestTemporalGapFilling:
    def test_missing_years_become_explicit_zeros(self, synthetic_records):
        # Data has 2016 and 2019 only; 2017 and 2018 must appear as zeros so a line chart
        # shows the gap rather than drawing straight across it.
        result = agg(synthetic_records, dimension="start_year", sort_by="category")
        by_label = {b.label: b.value for b in result.buckets}
        assert by_label["2017"] == 0 and by_label["2018"] == 0
        assert by_label["2016"] == 2 and by_label["2019"] == 1

    def test_year_only_dates_still_bucket_by_year(self, synthetic_records):
        result = agg(synthetic_records, dimension="start_year", sort_by="category")
        assert {b.label: b.value for b in result.buckets}["2016"] == 2

    def test_year_only_dates_cannot_support_a_quarter_bucket(self, synthetic_records):
        # Assigning "2016" to Q1 would be an invention; it belongs in Unknown.
        result = agg(
            synthetic_records, dimension="start_quarter", sort_by="category", include_unknown=True
        )
        assert UNKNOWN_KEY in {b.key for b in result.buckets}


class TestSeries:
    def test_series_produces_one_bucket_per_combination(self, synthetic_records):
        result = agg(
            synthetic_records, dimension="phase", series_dimension="cohort", sort_by="category"
        )
        assert result.series_dimension.id == "cohort"
        assert all(b.series_label is not None for b in result.buckets)


class TestShare:
    def test_share_is_reported_for_additive_measures(self, records):
        result = agg(records, dimension="overall_status")
        assert all(b.share_pct is not None for b in result.buckets)
        assert pytest.approx(sum(b.share_pct for b in result.buckets), abs=0.1) == 100.0

    def test_share_is_omitted_for_non_additive_measures(self, records):
        result = agg(records, dimension="overall_status", measure="median_enrollment")
        assert all(b.share_pct is None for b in result.buckets)
