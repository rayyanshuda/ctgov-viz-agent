"""Shared test fixtures.

Two sources of trial data are used deliberately:

``myeloma_page.json``
    120 real studies captured from the live API, so tests run against the messiness the
    service actually meets — 19 trials with no phase, 12 registered across two phases,
    22 multi-country, 29 with no MeSH intervention terms, and a mix of study types.

:func:`synthetic_records`
    Hand-built records pinning down edge cases the live sample happens not to contain,
    chiefly year-only dates and fully absent fields. Relying on a captured page to keep
    covering those would be luck, not testing.

Nothing here touches the network, and no API key is required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cache import ResponseCache
from app.config import Settings
from app.ctgov.normalize import Intervention, PartialDate, TrialRecord, normalize_study

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def raw_page() -> dict:
    return json.loads((FIXTURES / "myeloma_page.json").read_text())


@pytest.fixture(scope="session")
def records(raw_page: dict) -> list[TrialRecord]:
    return [r for s in raw_page["studies"] if (r := normalize_study(s, cohort="Myeloma"))]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="test-key-not-used",
        cache_dir=str(tmp_path / "cache"),
        max_studies=500,
    )


@pytest.fixture
def cache(tmp_path) -> ResponseCache:
    return ResponseCache(tmp_path / "cache", ttl_seconds=60)


def _record(nct: str, **kwargs) -> TrialRecord:
    return TrialRecord(nct_id=nct, brief_title=f"Study {nct}", **kwargs)


@pytest.fixture
def synthetic_records() -> list[TrialRecord]:
    """Records covering absence and partial precision explicitly."""
    return [
        _record(
            "NCT00000001",
            phases=("PHASE2",),
            start_date=PartialDate(2016, 4, 15, "2016-04-15"),
            countries=("United States", "Canada"),
            enrollment=100,
            lead_sponsor="Acme Pharmaceuticals, Inc.",
            intervention_meshes=("aspirin", "warfarin"),
            interventions=(Intervention("DRUG", "Aspirin"),),
        ),
        _record(
            "NCT00000002",
            phases=("PHASE2", "PHASE3"),  # spans two phases: counted in both
            start_date=PartialDate(2016, None, None, "2016"),  # year-only precision
            countries=("United States",),
            enrollment=250,
            lead_sponsor="Acme Pharma LLC",  # same sponsor, different legal suffix
            intervention_meshes=("aspirin",),
        ),
        _record(
            "NCT00000003",
            phases=(),  # no phase registered
            start_date=None,  # no start date at all
            countries=(),
            enrollment=None,  # never reported enrollment
            lead_sponsor=None,
            intervention_meshes=(),
        ),
        _record(
            "NCT00000004",
            phases=("PHASE3",),
            start_date=PartialDate(2019, 7, 1, "2019-07-01"),
            countries=("Japan",),
            enrollment=5000,
            lead_sponsor="Globex Corporation",
            intervention_meshes=("warfarin", "heparin"),
        ),
    ]


@pytest.fixture(autouse=True)
def no_accidental_network(request, monkeypatch):
    """Block real socket connections for every test not marked ``live``.

    Without this, a missing mock degrades into a silent live call: the test still
    passes, but slowly, non-deterministically, and against data that changes daily.
    That happened once during development — a test fell through to the real API and
    took 28 seconds — so the guarantee is enforced rather than assumed.
    """
    if "live" in request.keywords:
        return

    import socket

    def blocked(*args, **kwargs):
        raise RuntimeError(
            "This test attempted a real network connection. Mock the API with respx, or "
            "mark the test with @pytest.mark.live if it is meant to hit the live service."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
