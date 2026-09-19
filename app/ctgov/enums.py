# The fixed lists of values ClinicalTrials.gov accepts, including labels

# These were pulled from GET /api/v2/studies/enums instead of being typed from memory,
# so a filter value can be checked against what the API accepts.
# The labels exist because raw values like ACTIVE_NOT_RECRUITING don't belong on an axis.

from __future__ import annotations

# Ordered for display: phases ascending, "not applicable" last
PHASES: tuple[str, ...] = ("EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA")

STATUSES: tuple[str, ...] = (
    "ACTIVE_NOT_RECRUITING",
    "COMPLETED",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "SUSPENDED",
    "TERMINATED",
    "WITHDRAWN",
    "AVAILABLE",
    "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE",
    "APPROVED_FOR_MARKETING",
    "WITHHELD",
    "UNKNOWN",
)

STUDY_TYPES: tuple[str, ...] = ("INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS")

INTERVENTION_TYPES: tuple[str, ...] = (
    "BEHAVIORAL",
    "BIOLOGICAL",
    "COMBINATION_PRODUCT",
    "DEVICE",
    "DIAGNOSTIC_TEST",
    "DIETARY_SUPPLEMENT",
    "DRUG",
    "GENETIC",
    "PROCEDURE",
    "RADIATION",
    "OTHER",
)

SPONSOR_CLASSES: tuple[str, ...] = (
    "NIH",
    "FED",
    "OTHER_GOV",
    "INDIV",
    "INDUSTRY",
    "NETWORK",
    "AMBIG",
    "OTHER",
    "UNKNOWN",
)

PRIMARY_PURPOSES: tuple[str, ...] = (
    "TREATMENT",
    "PREVENTION",
    "DIAGNOSTIC",
    "ECT",
    "SUPPORTIVE_CARE",
    "SCREENING",
    "HEALTH_SERVICES_RESEARCH",
    "BASIC_SCIENCE",
    "DEVICE_FEASIBILITY",
    "OTHER",
)

ALLOCATIONS: tuple[str, ...] = ("RANDOMIZED", "NON_RANDOMIZED", "NA")
MASKINGS: tuple[str, ...] = ("NONE", "SINGLE", "DOUBLE", "TRIPLE", "QUADRUPLE")
SEXES: tuple[str, ...] = ("FEMALE", "MALE", "ALL")
STANDARD_AGES: tuple[str, ...] = ("CHILD", "ADULT", "OLDER_ADULT")

# Labels that plain title-casing would get wrong.
_LABEL_OVERRIDES: dict[str, str] = {
    "NA": "Not Applicable",
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation",
    "NOT_YET_RECRUITING": "Not yet recruiting",
    "NO_LONGER_AVAILABLE": "No longer available",
    "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available",
    "APPROVED_FOR_MARKETING": "Approved for marketing",
    "EXPANDED_ACCESS": "Expanded Access",
    "COMBINATION_PRODUCT": "Combination Product",
    "DIAGNOSTIC_TEST": "Diagnostic Test",
    "DIETARY_SUPPLEMENT": "Dietary Supplement",
    "HEALTH_SERVICES_RESEARCH": "Health Services Research",
    "DEVICE_FEASIBILITY": "Device Feasibility",
    "SUPPORTIVE_CARE": "Supportive Care",
    "BASIC_SCIENCE": "Basic Science",
    "ECT": "ECT",
    "NON_RANDOMIZED": "Non-randomized",
    "OLDER_ADULT": "Older Adult",
    "NIH": "NIH",
    "FED": "Federal",
    "OTHER_GOV": "Other Government",
    "INDIV": "Individual",
    "INDUSTRY": "Industry",
    "NETWORK": "Network",
    "AMBIG": "Ambiguous",
    "ALL": "All",
    "UNKNOWN": "Unknown",
    "NONE": "None (Open Label)",
}


def humanize(value: str) -> str:
    # Turn an enum value into something readable.
    # Anything without an override just gets title-cased, which is right for most of
    # them (TREATMENT becomes Treatment) without needing an entry for every value.
    if value in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[value]
    return value.replace("_", " ").title()
