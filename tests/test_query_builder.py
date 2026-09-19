"""Translation of filter specs into ClinicalTrials.gov query parameters.

The expression forms asserted here were each verified against the live API during
development; these tests lock in the shapes so a refactor cannot silently change the
semantics of a query.
"""

from __future__ import annotations

import pytest

from app.ctgov.query_builder import build_advanced_filter, build_params, value_clause
from app.models.plan import TrialFilterSpec


def spec(**kwargs) -> TrialFilterSpec:
    return TrialFilterSpec.model_validate(kwargs)


class TestSearchExpressions:
    def test_single_term_is_unquoted_to_keep_api_synonym_expansion(self):
        # Measured: `lung cancer` matches 14,553 studies, `"lung cancer"` only 13,326.
        assert build_params(spec(conditions=["lung cancer"]))["query.cond"] == "lung cancer"

    def test_multiple_terms_are_parenthesised_so_or_binds_between_them(self):
        params = build_params(spec(conditions=["lung cancer", "melanoma"]))
        assert params["query.cond"] == "(lung cancer) OR (melanoma)"

    def test_each_term_type_maps_to_its_own_search_area(self):
        params = build_params(
            spec(
                conditions=["melanoma"],
                interventions=["pembrolizumab"],
                sponsors=["Merck"],
                terms=["biomarker"],
                locations=["Boston"],
            )
        )
        assert params["query.cond"] == "melanoma"
        assert params["query.intr"] == "pembrolizumab"
        assert params["query.spons"] == "Merck"
        assert params["query.term"] == "biomarker"
        assert params["query.locn"] == "Boston"

    def test_blank_terms_are_dropped_rather_than_sent_as_empty(self):
        assert "query.cond" not in build_params(spec(conditions=["  "], terms=["x"]))


class TestAdvancedFilter:
    def test_absent_when_nothing_constrains_it(self):
        assert build_advanced_filter(spec(conditions=["melanoma"])) is None

    def test_enum_values_are_grouped_with_or(self):
        assert build_advanced_filter(spec(phases=["PHASE2", "PHASE3"])) == (
            "AREA[Phase](PHASE2 OR PHASE3)"
        )

    def test_single_enum_value_needs_no_parentheses(self):
        assert build_advanced_filter(spec(phases=["PHASE3"])) == "AREA[Phase]PHASE3"

    def test_country_names_are_quoted_because_they_contain_spaces(self):
        assert build_advanced_filter(spec(countries=["United States"])) == (
            'AREA[LocationCountry]"United States"'
        )

    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"start_year_min": 2015}, "AREA[StartDate]RANGE[2015-01-01,MAX]"),
            ({"start_year_max": 2020}, "AREA[StartDate]RANGE[MIN,2020-12-31]"),
            (
                {"start_year_min": 2015, "start_year_max": 2020},
                "AREA[StartDate]RANGE[2015-01-01,2020-12-31]",
            ),
        ],
    )
    def test_date_ranges_use_the_api_sentinels(self, kwargs, expected):
        assert build_advanced_filter(spec(**kwargs)) == expected

    def test_clauses_are_combined_with_and(self):
        built = build_advanced_filter(spec(phases=["PHASE3"], study_types=["INTERVENTIONAL"]))
        assert built == "AREA[Phase]PHASE3 AND AREA[StudyType]INTERVENTIONAL"

    def test_has_results_renders_as_a_boolean(self):
        assert build_advanced_filter(spec(has_results=True)) == "AREA[HasResults]true"
        assert build_advanced_filter(spec(has_results=False)) == "AREA[HasResults]false"


class TestInjectionSafety:
    def test_essie_metacharacters_are_stripped_from_free_text(self):
        # Without sanitising, this value would close the AREA clause and append its own.
        built = build_advanced_filter(spec(countries=["Boston] OR AREA[Phase"]))
        assert "AREA[Phase" not in built.replace('AREA[LocationCountry]', "")
        assert built.count("AREA[") == 1

    def test_quotes_cannot_escape_a_quoted_value(self):
        built = build_advanced_filter(spec(countries=['a" OR "b']))
        assert built.count('"') == 2


class TestRequestAssembly:
    def test_statuses_use_the_dedicated_filter_parameter(self):
        params = build_params(spec(statuses=["RECRUITING", "COMPLETED"], conditions=["x"]))
        assert params["filter.overallStatus"] == "RECRUITING,COMPLETED"

    def test_pagination_and_projection_are_passed_through(self):
        params = build_params(
            spec(conditions=["x"]),
            fields=["NCTId", "Phase"],
            page_size=500,
            count_total=True,
            page_token="tok",
        )
        assert params["fields"] == "NCTId,Phase"
        assert params["pageSize"] == "500"
        assert params["countTotal"] == "true"
        assert params["pageToken"] == "tok"

    def test_count_total_is_omitted_unless_requested(self):
        assert "countTotal" not in build_params(spec(conditions=["x"]))

    def test_extra_clause_is_appended_for_bucket_counting(self):
        params = build_params(spec(conditions=["x"]), extra_advanced="AREA[Phase]PHASE3")
        assert params["filter.advanced"] == "AREA[Phase]PHASE3"

    def test_extra_clause_composes_with_existing_filters(self):
        params = build_params(
            spec(conditions=["x"], study_types=["INTERVENTIONAL"]),
            extra_advanced="AREA[Phase]PHASE3",
        )
        assert params["filter.advanced"] == (
            "AREA[StudyType]INTERVENTIONAL AND AREA[Phase]PHASE3"
        )


class TestValueClause:
    def test_quotes_only_when_the_value_contains_a_space(self):
        assert value_clause("Phase", "PHASE3") == "AREA[Phase]PHASE3"
        assert value_clause("LocationCountry", "United States") == (
            'AREA[LocationCountry]"United States"'
        )


class TestFilterValidation:
    def test_a_cohort_must_constrain_something(self):
        with pytest.raises(ValueError, match="at least one filter"):
            spec()

    def test_reversed_year_range_is_rejected(self):
        with pytest.raises(ValueError, match="start_year_min"):
            spec(start_year_min=2020, start_year_max=2015)


class TestListCoercion:
    """A JSON array serialized as a string is a wire-format slip, not a schema violation.

    Recovering it avoids a repair round trip. The shape that motivated widening this was
    `'["a", "b"]}'` — trailing junk after a valid array, which an earlier version missed
    because it required the string to *end* with `]`.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('["a", "b"]', ["a", "b"]),
            ('["a", "b"]}', ["a", "b"]),
            ('  ["a"]  ', ["a"]),
            ("a single plain sentence", ["a single plain sentence"]),
            ("", []),
        ],
    )
    def test_string_shapes_are_recovered(self, raw, expected):
        assert spec(conditions=raw, terms=["x"]).conditions == expected

    def test_a_real_list_is_unchanged(self):
        assert spec(conditions=["a", "b"]).conditions == ["a", "b"]

    def test_unparseable_bracketed_text_is_left_to_fail_validation(self):
        # Text that looks like an array but will not parse is *not* guessed at. It is
        # passed through unchanged so Pydantic rejects it and the model is told why,
        # rather than being silently mangled into something plausible but wrong.
        with pytest.raises(ValueError, match="valid list"):
            spec(conditions="[unclosed", terms=["x"])
