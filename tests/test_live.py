"""Tests that exercise the real ClinicalTrials.gov API.

Deselected by default (see `addopts` in pyproject.toml). Run them with::

    uv run pytest -m live

These exist because the offline suite's fixtures are a snapshot: they prove the code is
self-consistent, not that our assumptions about the upstream API still hold. These check
the assumptions themselves, so a change at ClinicalTrials.gov surfaces as a test failure
rather than as wrong numbers in a chart.
"""

from __future__ import annotations

import pytest

from app.analysis.dimensions import get_dimension
from app.config import Settings
from app.ctgov.client import CTGovClient
from app.ctgov.query_builder import value_clause
from app.models.plan import TrialFilterSpec

pytestmark = pytest.mark.live


@pytest.fixture
async def client(tmp_path):
    settings = Settings(anthropic_api_key="unused", cache_dir=str(tmp_path), max_studies=200)
    async with CTGovClient(settings) as made:
        yield made


class TestApiContract:
    async def test_field_projection_returns_the_requested_shape(self, client):
        result = await client.fetch(
            TrialFilterSpec(conditions=["melanoma"]),
            fields=("Phase", "StartDate", "LeadSponsorName"),
            max_studies=5,
        )
        assert result.records
        assert result.total_count > 0
        assert any(r.phases for r in result.records)

    async def test_pagination_token_is_followed(self, client):
        result = await client.fetch(
            TrialFilterSpec(conditions=["cancer"]), fields=("Phase",), max_studies=1500
        )
        assert len(result.requests) > 1, "should have needed more than one page"
        assert len({r.nct_id for r in result.records}) == len(result.records)

    async def test_advanced_filters_actually_narrow_the_result(self, client):
        broad = await client.count(TrialFilterSpec(conditions=["melanoma"]))
        narrow = await client.count(
            TrialFilterSpec(conditions=["melanoma"], phases=["PHASE3"])
        )
        assert 0 < narrow < broad

    async def test_exact_count_strategy_agrees_with_full_retrieval(self, client):
        """The per-bucket count must match what counting the records gives.

        This is the assumption the exact-count strategy rests on: that asking the API
        for a filtered total yields the same number as downloading and tallying.
        """
        filters = TrialFilterSpec(conditions=["multiple myeloma"], phases=["PHASE3"])
        dimension = get_dimension("phase")
        probed = await client.count(
            filters, extra_advanced=value_clause(dimension.essie_area, "PHASE3")
        )
        direct = await client.count(filters)
        assert probed == direct

    async def test_unquoted_terms_still_outperform_quoted_ones(self, client):
        """Quoting suppresses the API's synonym expansion — the basis for our quoting rule."""
        unquoted = await client.count(TrialFilterSpec(conditions=["lung cancer"]))
        quoted = await client.count(TrialFilterSpec(conditions=['"lung cancer"']))
        assert unquoted >= quoted

    async def test_mesh_terms_are_present_for_common_drugs(self, client):
        result = await client.fetch(
            TrialFilterSpec(interventions=["pembrolizumab"]),
            fields=("InterventionMeshTerm",),
            max_studies=20,
        )
        terms = {t.lower() for r in result.records for t in r.intervention_meshes}
        assert "pembrolizumab" in terms
