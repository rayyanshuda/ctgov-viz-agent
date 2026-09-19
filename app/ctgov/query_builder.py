# Turns a filter spec into ClinicalTrials.gov query parameters

# Every expression built here was tested against the live API first

from __future__ import annotations

import re
from collections.abc import Sequence

from app.models.plan import TrialFilterSpec

# Characters with meaning in Essie expressions. Text reaching a filter clause is
# stripped of them so a value like 'Boston] OR AREA[Phase' cannot restructure the query.
_ESSIE_UNSAFE = re.compile(r'[\[\]()"]')


def _clean(value: str) -> str:
    # Strip characters that would break the query, and squash extra spaces
    return re.sub(r"\s+", " ", _ESSIE_UNSAFE.sub(" ", value)).strip()


def _search_expression(terms: Sequence[str]) -> str | None:
    # Join free-text terms for a query.* parameter.
    # One term is passed empty so the API expands synonyms. Several terms each get
    # brackets, so OR joins the terms rather than the words inside them.
    cleaned = [_clean(t) for t in terms if _clean(t)]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    return " OR ".join(f"({t})" for t in cleaned)


def _area_clause(area: str, values: Sequence[str], quote: bool = False) -> str | None:
    # Build an AREA[Field](...) clause.
    # Country names get quotes because they contain spaces.
    cleaned = [_clean(v) for v in values if _clean(v)]
    if not cleaned:
        return None
    rendered = [f'"{v}"' if quote else v for v in cleaned]
    if len(rendered) == 1:
        return f"AREA[{area}]{rendered[0]}"
    return f"AREA[{area}]({' OR '.join(rendered)})"


def _date_range_clause(year_min: int | None, year_max: int | None) -> str | None:
    # Start-date range clause, using the API's MIN and MAX keywords for open ends
    if year_min is None and year_max is None:
        return None
    low = f"{year_min}-01-01" if year_min is not None else "MIN"
    high = f"{year_max}-12-31" if year_max is not None else "MAX"
    return f"AREA[StartDate]RANGE[{low},{high}]"


def build_advanced_filter(filters: TrialFilterSpec, extra: str | None = None) -> str | None:
    # Put the filter.advanced expression together, or None if nothing constrains it
    clauses = [
        _area_clause("Phase", filters.phases),
        _area_clause("StudyType", filters.study_types),
        _area_clause("InterventionType", filters.intervention_types),
        _area_clause("LeadSponsorClass", filters.sponsor_classes),
        _area_clause("LocationCountry", filters.countries, quote=True),
        _date_range_clause(filters.start_year_min, filters.start_year_max),
    ]
    if filters.has_results is not None:
        clauses.append(f"AREA[HasResults]{'true' if filters.has_results else 'false'}")
    if extra:
        clauses.append(extra)
    present = [c for c in clauses if c]
    return " AND ".join(present) if present else None


def build_params(
    filters: TrialFilterSpec,
    *,
    fields: Sequence[str] = (),
    page_size: int = 1000,
    count_total: bool = False,
    page_token: str | None = None,
    extra_advanced: str | None = None,
) -> dict[str, str]:
    # Build the full query string for GET /studies.
    # extra_advanced adds one more clause, which is how the exact-count strategy asks
    # "how many of these are Phase 3?" without downloading any studies.
    params: dict[str, str] = {}

    for key, terms in (
        ("query.cond", filters.conditions),
        ("query.intr", filters.interventions),
        ("query.spons", filters.sponsors),
        ("query.term", filters.terms),
        ("query.locn", filters.locations),
    ):
        expression = _search_expression(terms)
        if expression:
            params[key] = expression

    if filters.statuses:
        params["filter.overallStatus"] = ",".join(filters.statuses)

    advanced = build_advanced_filter(filters, extra=extra_advanced)
    if advanced:
        params["filter.advanced"] = advanced

    if fields:
        params["fields"] = ",".join(fields)
    params["pageSize"] = str(page_size)
    if count_total:
        params["countTotal"] = "true"
    if page_token:
        params["pageToken"] = page_token
    return params


def value_clause(essie_area: str, value: str) -> str:
    # One AREA[field]value clause, used to ask the API for the size of a single bucket
    cleaned = _clean(value)
    return f'AREA[{essie_area}]"{cleaned}"' if " " in cleaned else f"AREA[{essie_area}]{cleaned}"
