"""Citations: verbatim excerpts, deduplication, and reproducible sampling."""

from __future__ import annotations

from app.analysis.aggregate import Contribution
from app.analysis.citations import index_citations, sample_citations
from app.analysis.dimensions import get_dimension


def contributions(records, excerpt="PHASE2"):
    return [Contribution(record=r, excerpt=excerpt) for r in records]


class TestSampling:
    def test_respects_the_limit(self, records):
        cites = sample_citations(contributions(records), source_field="f", limit=3)
        assert len(cites) == 3

    def test_zero_limit_returns_nothing(self, records):
        assert sample_citations(contributions(records), source_field="f", limit=0) == []

    def test_empty_input_returns_nothing(self):
        assert sample_citations([], source_field="f", limit=3) == []

    def test_is_deterministic_across_input_orderings(self, records):
        forward = sample_citations(contributions(records), source_field="f", limit=5)
        backward = sample_citations(
            contributions(list(reversed(records))), source_field="f", limit=5
        )
        assert [c.nct_id for c in forward] == [c.nct_id for c in backward], (
            "citation choice must not depend on retrieval order, or example runs "
            "would not reproduce"
        )

    def test_one_trial_is_cited_once_even_if_it_contributes_twice(self, records):
        doubled = contributions(records[:2]) + contributions(records[:2])
        cites = sample_citations(doubled, source_field="f", limit=10)
        assert len(cites) == 2


class TestContent:
    def test_excerpt_is_the_verbatim_api_value(self, records):
        cites = sample_citations(
            contributions(records[:1], excerpt="PHASE3"), source_field="x", limit=1
        )
        assert cites[0].excerpt == "PHASE3"

    def test_context_quotes_the_real_trial_title(self, records):
        cites = sample_citations(contributions(records[:1]), source_field="x", limit=1)
        assert records[0].brief_title.startswith(cites[0].context[:40])

    def test_source_field_is_recorded_for_traceability(self, records):
        field = get_dimension("phase").source_field
        cites = sample_citations(contributions(records[:1]), source_field=field, limit=1)
        assert cites[0].field == "protocolSection.designModule.phases"

    def test_url_points_at_the_public_record(self, records):
        cites = sample_citations(contributions(records[:1]), source_field="x", limit=1)
        assert cites[0].url == f"https://clinicaltrials.gov/study/{cites[0].nct_id}"

    def test_long_context_is_truncated_at_a_word_boundary(self, records):
        long_title = next((r for r in records if len(r.brief_title) > 200), None)
        if long_title is None:
            return
        cites = sample_citations(contributions([long_title]), source_field="x", limit=1)
        assert cites[0].context.endswith("…")
        assert len(cites[0].context) <= 185


class TestIndex:
    def test_builds_one_entry_per_trial(self, records):
        cites = sample_citations(contributions(records), source_field="x", limit=5)
        index = index_citations(cites, {r.nct_id: r.brief_title for r in records})
        assert len(index) == 5
        assert all(entry.url.startswith("https://") for entry in index.values())

    def test_repeated_citations_collapse_to_one_entry(self, records):
        cites = sample_citations(contributions(records[:1]), source_field="x", limit=1) * 3
        assert len(index_citations(cites, {})) == 1
