# Deep citations: attach source references to aggregated data

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.analysis.aggregate import Contribution
from app.models.response import Citation, CitationIndexEntry

_CONTEXT_MAX_CHARS = 180


def _truncate(text: str, limit: int = _CONTEXT_MAX_CHARS) -> str:
    # Shorten at a word boundary, marking that text was cut.
    text = text.strip()
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return f"{clipped}…"


def sample_citations(
    contributions: Sequence[Contribution],
    *,
    source_field: str,
    limit: int,
) -> list[Citation]:
    if limit <= 0 or not contributions:
        return []

    by_trial: dict[str, Contribution] = {}
    for contribution in contributions:
        by_trial.setdefault(contribution.record.nct_id, contribution)

    chosen = sorted(by_trial)[:limit]
    return [
        Citation(
            nct_id=nct_id,
            field=source_field,
            excerpt=_truncate(by_trial[nct_id].excerpt),
            context=_truncate(by_trial[nct_id].record.brief_title),
            url=by_trial[nct_id].record.url,
        )
        for nct_id in chosen
    ]


def index_citations(citations: Iterable[Citation], titles: dict[str, str]) -> dict[
    str, CitationIndexEntry

    # maps NCT ID to title/URL

    # Titles are repeated across citations, so they are pulled here once
]:
    index: dict[str, CitationIndexEntry] = {}
    for citation in citations:
        if citation.nct_id not in index:
            index[citation.nct_id] = CitationIndexEntry(
                title=titles.get(citation.nct_id, citation.context),
                url=citation.url,
            )
    return index
