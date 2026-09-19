# Tools the planner can call on before it commits to a plan

# Important functions, so the model does not start guessing what abbreviations the ClinicalTrials.gov uses
# These tools let the model check data (e.g. how many trials a term actually matches, what the regisry calls a drug, which sponsors appear.)
# This the most hallucinating prone step because the model can make-up random guesses

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from app.analysis.dimensions import DIMENSION_IDS, UNKNOWN_KEY, get_dimension
from app.ctgov.client import CTGovClient
from app.models.plan import TrialFilterSpec

logger = logging.getLogger(__name__)

_RESOLVE_SAMPLE = 60
_VALUES_SAMPLE = 400

_ENTITY_FIELD = {"drug": "interventions", "condition": "conditions", "sponsor": "sponsors"}


def tool_definitions() -> list[dict[str, Any]]:
    # JSON schemas for the probe tools, not including "submit_plan"
    # "submit_plan" is defined in :mod:`app.agent.planner`, since its schema is generated from the plan model

    filter_schema = {
        "type": "object",
        "description": "A subset of TrialFilterSpec: the filters to test.",
        "properties": {
            "conditions": {"type": "array", "items": {"type": "string"}},
            "interventions": {"type": "array", "items": {"type": "string"}},
            "sponsors": {"type": "array", "items": {"type": "string"}},
            "terms": {"type": "array", "items": {"type": "string"}},
            "countries": {"type": "array", "items": {"type": "string"}},
            "phases": {"type": "array", "items": {"type": "string"}},
            "statuses": {"type": "array", "items": {"type": "string"}},
            "study_types": {"type": "array", "items": {"type": "string"}},
            "start_year_min": {"type": "integer"},
            "start_year_max": {"type": "integer"},
        },
    }

    return [
        {
            "name": "resolve_entity",
            "description": (
                "Check how ClinicalTrials.gov indexes a drug, condition or sponsor "
                "name before you filter on it. Returns the number of matching trials and the "
                "normalized MeSH terms or sponsor names that appear in them. Use this whenever "
                "the question names something you are not certain the registry spells the same "
                "way — brand names (Keytruda), abbreviations (NSCLC), or informal sponsor names "
                "(Merck). A term that returns 0 matches is a filter that will silently produce "
                "an empty chart."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["drug", "condition", "sponsor"],
                        "description": "Which search area to test the term against.",
                    },
                    "text": {"type": "string", "description": "The term as the user wrote it."},
                },
                "required": ["kind", "text"],
            },
        },
        {
            "name": "preview_result_size",
            "description": (
                "Count the trials a set of filters would match, without retrieving them. Use it "
                "to check that a cohort is neither empty nor so broad the analysis is "
                "meaningless, and to compare cohort sizes before committing to a comparison."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"filters": filter_schema},
                "required": ["filters"],
            },
        },
        {
            "name": "list_dimension_values",
            "description": (
                "Show the most common actual values of a dimension within a set of filters, "
                "from a sample of matching trials. Use it to pick a sensible top_k for a "
                "high-cardinality dimension (sponsors, drugs, conditions), to confirm a "
                "dimension is populated at all, or to see the real vocabulary before choosing "
                "network endpoints. Counts are indicative, from a sample — not final answers."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "filters": filter_schema,
                    "dimension": {"type": "string", "enum": list(DIMENSION_IDS)},
                    "top_n": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                },
                "required": ["filters", "dimension"],
            },
        },
    ]


class ToolExecutor:
    # Run the probe tools on the live API

    def __init__(self, client: CTGovClient) -> None:
        self.client = client

    async def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Send a tool call, such that the errors are returned as data
        # A failed probe teaches the model and lets it continue

        try:
            if name == "resolve_entity":
                return await self._resolve_entity(arguments["kind"], arguments["text"])
            if name == "preview_result_size":
                return await self._preview_result_size(arguments.get("filters") or {})
            if name == "list_dimension_values":
                return await self._list_dimension_values(
                    arguments.get("filters") or {},
                    arguments["dimension"],
                    int(arguments.get("top_n", 10)),
                )
            return {"error": f"unknown tool {name!r}"}
        except Exception as exc:
            logger.warning("Probe tool %s failed", name, exc_info=True)
            return {"error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _parse_filters(raw: dict[str, Any]) -> TrialFilterSpec | dict[str, Any]:
        try:
            return TrialFilterSpec.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"invalid filters: {exc}"}

    async def _resolve_entity(self, kind: str, text: str) -> dict[str, Any]:
        field = _ENTITY_FIELD.get(kind)
        if field is None:
            return {"error": f"kind must be one of {sorted(_ENTITY_FIELD)}"}

        filters = TrialFilterSpec.model_validate({field: [text]})
        total = await self.client.count(filters)
        if total == 0:
            return {
                "query": text,
                "kind": kind,
                "matching_trials": 0,
                "advice": "This term matches no trials. Try a generic drug name instead of a "
                "brand name, a fuller condition name, or put it in `terms` for a free-text "
                "search instead of a typed field.",
            }

        result = await self.client.fetch(
            filters,
            fields=("InterventionMeshTerm", "ConditionMeshTerm", "LeadSponsorName"),
            max_studies=_RESOLVE_SAMPLE,
        )

        payload: dict[str, Any] = {
            "query": text,
            "kind": kind,
            "matching_trials": total,
            "sampled": len(result.records),
        }
        if kind in {"drug", "condition"}:
            attribute = "intervention_meshes" if kind == "drug" else "condition_meshes"
            counter: Counter[str] = Counter()
            for record in result.records:
                counter.update(getattr(record, attribute))
            payload["normalized_mesh_terms"] = [
                {"term": term, "trials_in_sample": count} for term, count in counter.most_common(8)
            ]
            payload["advice"] = (
                "Keep the user's original term in the filter — the API expands synonyms "
                "already. Use these MeSH terms when you need a grouping dimension "
                f"({'intervention_mesh' if kind == 'drug' else 'condition_mesh'}) or network node."
            )
        else:
            counter = Counter(r.lead_sponsor for r in result.records if r.lead_sponsor)
            payload["sponsor_names_found"] = [
                {"name": name, "trials_in_sample": count} for name, count in counter.most_common(8)
            ]
        return payload

    async def _preview_result_size(self, raw_filters: dict[str, Any]) -> dict[str, Any]:
        filters = self._parse_filters(raw_filters)
        if isinstance(filters, dict):
            return filters
        total = await self.client.count(filters)
        if total == 0:
            advice = "No trials match. Loosen or drop a filter before planning around this."
        elif total < 15:
            advice = (
                f"Only {total} trials match. A breakdown will be very sparse; consider widening "
                "the filters or choosing a kpi/table visualization instead of a chart."
            )
        elif total > 20_000:
            advice = (
                f"{total:,} trials match — very broad. Narrowing improves both speed and "
                "meaning, though exact bucket counts are still available for enum dimensions."
            )
        else:
            advice = f"{total:,} trials match, a workable size."
        return {"matching_trials": total, "advice": advice}

    async def _list_dimension_values(
        self, raw_filters: dict[str, Any], dimension_id: str, top_n: int
    ) -> dict[str, Any]:
        filters = self._parse_filters(raw_filters)
        if isinstance(filters, dict):
            return filters
        try:
            dimension = get_dimension(dimension_id)
        except KeyError as exc:
            return {"error": str(exc)}

        result = await self.client.fetch(
            filters, fields=dimension.api_fields, max_studies=_VALUES_SAMPLE
        )
        counter: Counter[str] = Counter()
        unknown = 0
        for record in result.records:
            for value in dimension.extract(record):
                if value.key == UNKNOWN_KEY:
                    unknown += 1
                else:
                    counter[value.label] += 1

        return {
            "dimension": dimension_id,
            "matching_trials": result.total_count,
            "sampled": len(result.records),
            "distinct_values_in_sample": len(counter),
            "top_values": [
                {"value": label, "trials_in_sample": count}
                for label, count in counter.most_common(top_n)
            ],
            "trials_missing_this_field": unknown,
            "multi_valued": dimension.multi_valued,
        }
