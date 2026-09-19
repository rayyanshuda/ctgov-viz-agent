# Turns the raw study JSON from ClinicalTrials.gov into a flat record

# The API payload is nested and not filled in consistently: dates can be
# year-only, phases can be missing or ["NA"], and several fields are arrays whose
# length changes per study. Everything downstream reads TrialRecord instead of the raw
# JSON, so all of that mess is dealt with once

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CTGOV_STUDY_URL = "https://clinicaltrials.gov/study/{nct_id}"

# Trailing corporate suffixes stripped when building a matching key for org names,
# so "Merck Sharp & Dohme LLC" and "Merck Sharp & Dohme, Inc." collapse to one node.
# Deliberately conservative: only well-known legal forms, only at the end of a name.
_LEGAL_SUFFIXES = (
    "inc",
    "inc.",
    "llc",
    "l.l.c.",
    "ltd",
    "ltd.",
    "limited",
    "corp",
    "corp.",
    "corporation",
    "co",
    "co.",
    "company",
    "gmbh",
    "ag",
    "sa",
    "s.a.",
    "nv",
    "n.v.",
    "bv",
    "b.v.",
    "plc",
    "ab",
    "as",
    "a/s",
    "aps",
    "oy",
    "pty",
    "pty.",
    "spa",
    "s.p.a.",
    "srl",
    "s.r.l.",
    "kk",
    "k.k.",
    "pharmaceuticals",
    "pharmaceutical",
    "pharma",
)


@dataclass(frozen=True, slots=True)
class PartialDate:
    # A date that might only have a year, or a year and month.
    # The API returns "2016", "2016-04" or "2016-04-15" depending on what the sponsor
    # registered. Keep whatever precision was given and hold on to the original
    # string in raw, so a citation can quote what the API said.

    year: int
    month: int | None
    day: int | None
    raw: str

    @property
    def quarter(self) -> int | None:
        return None if self.month is None else (self.month - 1) // 3 + 1

    @classmethod
    def parse(cls, value: str | None) -> PartialDate | None:
        # Read an API date string, or return None if it is missing or unreadable
        if not value:
            return None
        match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$", value.strip())
        if not match:
            return None
        year, month, day = match.groups()
        return cls(
            year=int(year),
            month=int(month) if month else None,
            day=int(day) if day else None,
            raw=value.strip(),
        )


@dataclass(frozen=True, slots=True)
class Intervention:
    # One intervention on a trial: its type (DRUG, DEVICE, ...) and its name

    type: str | None
    name: str


@dataclass(frozen=True, slots=True)
class TrialRecord:
    # One clinical trial, flattened down to the fields this service can visualize.
    # cohort is set by the retrieval layer, not API. When a question compares two
    # things, each side is fetched as its own named cohort and the label is attached to
    # every record, so it can be grouped on like any other dimension.

    nct_id: str
    brief_title: str
    cohort: str = ""

    overall_status: str | None = None
    study_type: str | None = None
    phases: tuple[str, ...] = ()
    has_results: bool = False

    start_date: PartialDate | None = None
    completion_date: PartialDate | None = None
    primary_completion_date: PartialDate | None = None

    lead_sponsor: str | None = None
    lead_sponsor_class: str | None = None
    collaborators: tuple[str, ...] = ()

    conditions: tuple[str, ...] = ()
    condition_meshes: tuple[str, ...] = ()

    interventions: tuple[Intervention, ...] = ()
    intervention_meshes: tuple[str, ...] = ()

    countries: tuple[str, ...] = ()

    enrollment: int | None = None
    enrollment_type: str | None = None

    primary_purpose: str | None = None
    allocation: str | None = None
    masking: str | None = None
    sex: str | None = None
    std_ages: tuple[str, ...] = ()

    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return CTGOV_STUDY_URL.format(nct_id=self.nct_id)


def org_key(name: str) -> str:
    # Reduce an organization name to a key used for matching.
    # Lowercases and drops punctuation and trailing legal suffixes, so "Merck Sharp &
    # Dohme LLC" and "Merck Sharp & Dohme, Inc." become one node. The original name is
    # still shown to the user; this value is only used for grouping.
    cleaned = re.sub(r"[^\w\s&]", " ", name.lower())
    tokens = [t for t in cleaned.split() if t]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens) if tokens else name.lower().strip()


def _dedupe(values: list[str]) -> tuple[str, ...]:
    # Remove duplicates ignoring case, keeping the original order
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value:
            continue
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(value.strip())
    return tuple(out)


def normalize_study(study: dict[str, Any], cohort: str = "") -> TrialRecord | None:
    # Convert one raw study from the API into a TrialRecord.
    # Returns None if the study has no NCT ID, which should not happen, but would
    # otherwise leave a record that nothing could cite.
    protocol = study.get("protocolSection") or {}
    derived = study.get("derivedSection") or {}

    identification = protocol.get("identificationModule") or {}
    nct_id = identification.get("nctId")
    if not nct_id:
        return None

    status = protocol.get("statusModule") or {}
    sponsor_module = protocol.get("sponsorCollaboratorsModule") or {}
    lead = sponsor_module.get("leadSponsor") or {}
    conditions_module = protocol.get("conditionsModule") or {}
    design = protocol.get("designModule") or {}
    design_info = design.get("designInfo") or {}
    enrollment_info = design.get("enrollmentInfo") or {}
    arms = protocol.get("armsInterventionsModule") or {}
    eligibility = protocol.get("eligibilityModule") or {}
    locations_module = protocol.get("contactsLocationsModule") or {}

    interventions = tuple(
        Intervention(type=item.get("type"), name=item["name"].strip())
        for item in (arms.get("interventions") or [])
        if item.get("name")
    )

    countries = _dedupe(
        [loc.get("country", "") for loc in (locations_module.get("locations") or [])]
    )

    condition_meshes = _dedupe(
        [m.get("term", "") for m in ((derived.get("conditionBrowseModule") or {}).get("meshes") or [])]
    )
    intervention_meshes = _dedupe(
        [
            m.get("term", "")
            for m in ((derived.get("interventionBrowseModule") or {}).get("meshes") or [])
        ]
    )

    return TrialRecord(
        nct_id=nct_id,
        brief_title=(identification.get("briefTitle") or "").strip(),
        cohort=cohort,
        overall_status=status.get("overallStatus"),
        study_type=design.get("studyType"),
        phases=tuple(design.get("phases") or ()),
        has_results=bool(study.get("hasResults", False)),
        start_date=PartialDate.parse((status.get("startDateStruct") or {}).get("date")),
        completion_date=PartialDate.parse((status.get("completionDateStruct") or {}).get("date")),
        primary_completion_date=PartialDate.parse(
            (status.get("primaryCompletionDateStruct") or {}).get("date")
        ),
        lead_sponsor=(lead.get("name") or "").strip() or None,
        lead_sponsor_class=lead.get("class"),
        collaborators=_dedupe(
            [c.get("name", "") for c in (sponsor_module.get("collaborators") or [])]
        ),
        conditions=_dedupe(list(conditions_module.get("conditions") or [])),
        condition_meshes=condition_meshes,
        interventions=interventions,
        intervention_meshes=intervention_meshes,
        countries=countries,
        enrollment=enrollment_info.get("count"),
        enrollment_type=enrollment_info.get("type"),
        primary_purpose=design_info.get("primaryPurpose"),
        allocation=design_info.get("allocation"),
        masking=(design_info.get("maskingInfo") or {}).get("masking"),
        sex=eligibility.get("sex"),
        std_ages=tuple(eligibility.get("stdAges") or ()),
    )
