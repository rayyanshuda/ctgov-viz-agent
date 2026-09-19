"""The dimension and measure registries, and their extractors."""

from __future__ import annotations

import pytest

from app.analysis.dimensions import (
    DIMENSIONS,
    UNKNOWN_KEY,
    get_dimension,
    required_api_fields,
)
from app.analysis.measures import MEASURES, METRICS, get_measure, get_metric
from app.ctgov.countries import iso3_for


class TestRegistryInvariants:
    @pytest.mark.parametrize("dimension", DIMENSIONS.values(), ids=lambda d: d.id)
    def test_every_dimension_is_well_formed(self, dimension):
        assert dimension.label and dimension.description
        assert dimension.source_field
        assert dimension.kind in {"nominal", "ordinal", "temporal", "quantitative"}
        # 'cohort' is synthesized from the query, so it needs no API field.
        assert dimension.api_fields or dimension.id == "cohort"

    @pytest.mark.parametrize("dimension", DIMENSIONS.values(), ids=lambda d: d.id)
    def test_every_extractor_handles_a_bare_record(self, dimension, synthetic_records):
        # The third synthetic record reports almost nothing; no extractor may raise on it.
        values = dimension.extract(synthetic_records[2])
        assert values, f"{dimension.id} must return a bucket even when the field is absent"

    @pytest.mark.parametrize("dimension", DIMENSIONS.values(), ids=lambda d: d.id)
    def test_extracted_values_always_carry_an_excerpt(self, dimension, records):
        for record in records[:20]:
            for value in dimension.extract(record):
                assert value.key and value.label and value.source_excerpt

    def test_exact_count_support_requires_both_enum_and_search_area(self):
        for dimension in DIMENSIONS.values():
            if dimension.supports_exact_counts:
                assert dimension.enum_values and dimension.essie_area

    def test_network_eligible_dimensions_are_entities_not_design_attributes(self):
        eligible = {d.id for d in DIMENSIONS.values() if d.network_eligible}
        assert {"lead_sponsor", "intervention_mesh", "condition_mesh", "country"} <= eligible
        assert not ({"phase", "overall_status", "masking", "sex", "cohort"} & eligible)

    def test_unknown_dimension_error_lists_the_alternatives(self):
        with pytest.raises(KeyError, match="lead_sponsor"):
            get_dimension("sponsor_country")

    def test_unknown_measure_error_lists_the_alternatives(self):
        with pytest.raises(KeyError, match="trial_count"):
            get_measure("count")


class TestProjection:
    def test_unions_the_fields_needed(self):
        fields = required_api_fields(["phase", "start_year", "country"])
        assert set(fields) == {"Phase", "StartDate", "LocationCountry"}

    def test_deduplicates_shared_fields(self):
        fields = required_api_fields(["start_year", "start_quarter", "start_month"])
        assert fields == ("StartDate",)

    def test_cohort_needs_nothing_from_the_api(self):
        assert required_api_fields(["cohort"]) == ()


class TestExtractors:
    def test_phase_returns_one_bucket_per_registered_phase(self, synthetic_records):
        values = get_dimension("phase").extract(synthetic_records[1])
        assert {v.key for v in values} == {"PHASE2", "PHASE3"}

    def test_missing_phase_becomes_unknown_with_a_reason(self, synthetic_records):
        value = get_dimension("phase").extract(synthetic_records[2])[0]
        assert value.key == UNKNOWN_KEY
        assert "no phase registered" in value.source_excerpt

    def test_start_year_cites_the_full_date_it_was_derived_from(self, synthetic_records):
        value = get_dimension("start_year").extract(synthetic_records[0])[0]
        assert value.key == "2016"
        assert value.source_excerpt == "2016-04-15", (
            "the citation must quote what the API said, not the derived bucket"
        )

    def test_quarter_is_not_invented_from_a_year_only_date(self, synthetic_records):
        value = get_dimension("start_quarter").extract(synthetic_records[1])[0]
        assert value.key == UNKNOWN_KEY
        assert "year precision" in value.source_excerpt

    def test_sponsor_variants_share_a_key_but_keep_their_own_label(self, synthetic_records):
        first = get_dimension("lead_sponsor").extract(synthetic_records[0])[0]
        second = get_dimension("lead_sponsor").extract(synthetic_records[1])[0]
        assert first.key == second.key
        assert first.label == "Acme Pharmaceuticals, Inc."

    def test_country_rows_carry_an_iso3_code(self, synthetic_records):
        values = get_dimension("country").extract(synthetic_records[0])
        assert {v.extra["country_iso3"] for v in values} == {"USA", "CAN"}

    def test_enrollment_bands_are_ordered_and_cite_the_raw_number(self, synthetic_records):
        value = get_dimension("enrollment_bucket").extract(synthetic_records[0])[0]
        assert value.key == "100-499"
        assert value.source_excerpt == "100"

    def test_cohort_uses_the_retrieval_label(self, records):
        assert get_dimension("cohort").extract(records[0])[0].label == "Myeloma"


class TestMeasures:
    def test_trial_count_counts_records(self, records):
        assert get_measure("trial_count").compute(records) == len(records)

    def test_enrollment_measures_ignore_trials_that_reported_none(self, synthetic_records):
        # 100, 250 and 5000 are reported; one trial reported nothing.
        assert get_measure("total_enrollment").compute(synthetic_records) == 5350
        assert get_measure("median_enrollment").compute(synthetic_records) == 250

    def test_measures_over_an_empty_set_are_honest(self):
        assert get_measure("trial_count").compute([]) == 0
        assert get_measure("median_enrollment").compute([]) is None, (
            "no trials means no median, not a median of zero"
        )

    def test_distinct_sponsor_count_uses_normalized_names(self, synthetic_records):
        # Acme Pharmaceuticals Inc. and Acme Pharma LLC are one sponsor; Globex is another.
        assert get_measure("distinct_sponsor_count").compute(synthetic_records) == 2


class TestMetrics:
    def test_duration_is_none_without_both_endpoints(self, synthetic_records):
        assert get_metric("duration_months").extract(synthetic_records[0]) is None

    def test_country_count_reflects_distinct_countries(self, synthetic_records):
        assert get_metric("country_count").extract(synthetic_records[0]) == 2.0

    @pytest.mark.parametrize("metric", METRICS.values(), ids=lambda m: m.id)
    def test_every_metric_tolerates_a_bare_record(self, metric, synthetic_records):
        assert metric.extract(synthetic_records[2]) is None


class TestCountries:
    def test_maps_the_names_the_api_actually_uses(self):
        assert iso3_for("United States") == "USA"
        assert iso3_for("South Korea") == "KOR"
        assert iso3_for("Turkey (Türkiye)") == "TUR"

    def test_dissolved_states_have_no_code(self):
        # Present in the data, but no current ISO3 exists; None must flow through rather
        # than the trial being dropped.
        assert iso3_for("Netherlands Antilles") is None
        assert iso3_for("Serbia and Montenegro") is None
