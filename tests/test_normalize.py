"""Normalization of raw API JSON, especially where fields are absent or imprecise."""

from __future__ import annotations

import pytest

from app.ctgov.normalize import PartialDate, TrialRecord, normalize_study, org_key


class TestPartialDate:
    @pytest.mark.parametrize(
        ("raw", "year", "month", "day"),
        [
            ("2016", 2016, None, None),
            ("2016-04", 2016, 4, None),
            ("2016-04-15", 2016, 4, 15),
            (" 2016-04 ", 2016, 4, None),
        ],
    )
    def test_parses_each_precision(self, raw, year, month, day):
        date = PartialDate.parse(raw)
        assert (date.year, date.month, date.day) == (year, month, day)
        assert date.raw == raw.strip(), "raw text is preserved verbatim for citations"

    @pytest.mark.parametrize("raw", [None, "", "not-a-date", "16-04", "2016/04/15"])
    def test_unparseable_is_none_not_an_error(self, raw):
        assert PartialDate.parse(raw) is None

    def test_quarter_requires_a_month(self):
        assert PartialDate.parse("2016-04").quarter == 2
        assert PartialDate.parse("2016-12").quarter == 4
        assert PartialDate.parse("2016").quarter is None


class TestOrgKey:
    def test_collapses_legal_suffix_variants(self):
        assert org_key("Acme Pharmaceuticals, Inc.") == org_key("Acme Pharmaceuticals LLC")
        assert org_key("Merck Sharp & Dohme Corp.") == org_key("Merck Sharp & Dohme LLC")

    def test_keeps_genuinely_different_orgs_apart(self):
        assert org_key("Acme Pharma") != org_key("Globex Pharma")
        assert org_key("University of Texas") != org_key("University of Toronto")

    def test_preserves_ampersands_within_a_name(self):
        assert "&" in org_key("Merck Sharp & Dohme")

    def test_name_that_is_only_a_suffix_survives(self):
        # Stripping every token would leave an empty key that merges unrelated sponsors.
        assert org_key("Pharma") != ""


class TestNormalizeStudy:
    def test_study_without_an_nct_id_is_dropped(self):
        assert normalize_study({"protocolSection": {"identificationModule": {}}}) is None

    def test_missing_modules_do_not_raise(self):
        record = normalize_study(
            {"protocolSection": {"identificationModule": {"nctId": "NCT1", "briefTitle": "T"}}}
        )
        assert isinstance(record, TrialRecord)
        assert record.phases == () and record.countries == () and record.enrollment is None
        assert record.start_date is None

    def test_cohort_tag_is_applied(self):
        record = normalize_study(
            {"protocolSection": {"identificationModule": {"nctId": "NCT1", "briefTitle": "T"}}},
            cohort="Arm A",
        )
        assert record.cohort == "Arm A"

    def test_url_is_derived_from_the_id(self):
        record = normalize_study(
            {"protocolSection": {"identificationModule": {"nctId": "NCT042", "briefTitle": "T"}}}
        )
        assert record.url == "https://clinicaltrials.gov/study/NCT042"

    def test_countries_are_deduplicated_across_sites(self):
        record = normalize_study(
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT1", "briefTitle": "T"},
                    "contactsLocationsModule": {
                        "locations": [
                            {"country": "United States", "city": "Boston"},
                            {"country": "United States", "city": "Austin"},
                            {"country": "Canada", "city": "Toronto"},
                        ]
                    },
                }
            }
        )
        assert record.countries == ("United States", "Canada")

    def test_real_page_normalizes_completely(self, raw_page, records):
        assert len(records) == len(raw_page["studies"])
        assert all(r.nct_id.startswith("NCT") for r in records)
        assert all(r.brief_title for r in records)

    def test_real_page_exercises_the_awkward_cases(self, records):
        # Guards the fixture itself: if a future refresh loses this variety, the tests
        # built on it quietly stop testing anything.
        assert any(not r.phases for r in records), "expected trials with no phase"
        assert any(len(r.phases) > 1 for r in records), "expected multi-phase trials"
        assert any(r.enrollment is None for r in records), "expected missing enrollment"
        assert any(len(r.countries) > 1 for r in records), "expected multi-country trials"
