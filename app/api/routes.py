# HTTP endpoints

# Wire the planner to the executor, and returns a model
# Judgement for the model lives in the agent folder and the executor.py file

# The capabiliities function publishes the dimension, measure, metrics, and visualization registries as data.
# So a frontend can built the filter UI (after I make the UI) and render from that, instead of hard coding a list

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.agent.planner import LLMPlanner, PlanningResult
from app.api.ratelimit import enforce_rate_limit
from app.analysis.dimensions import DIMENSIONS
from app.analysis.measures import MEASURES, METRICS
from app.config import Settings
from app.ctgov.client import CTGovClient
from app.ctgov.enums import (
    INTERVENTION_TYPES,
    PHASES,
    SPONSOR_CLASSES,
    STATUSES,
    STUDY_TYPES,
)
from app.executor import PlanExecutor
from app.models.plan import AnalysisPlan, VisualizationType
from app.models.request import VisualizeRequest
from app.models.response import CapabilitiesResponse, VisualizeResponse
from app.viz.compatibility import ALLOWED_TYPES

router = APIRouter()


def _client(request: Request) -> CTGovClient:
    return request.app.state.ctgov_client


def _settings(request: Request) -> Settings:
    return request.app.state.settings


async def _plan(request: Request, payload: VisualizeRequest) -> PlanningResult:
    planner = LLMPlanner(_settings(request), _client(request))
    return await planner.plan(payload)


@router.post(
    "/visualize",
    response_model=VisualizeResponse,
    response_model_exclude_none=True,
    summary="Answer a question with a visualization specification",
    description=(
        "Interprets the question, retrieves matching trials from ClinicalTrials.gov, computes "
        "the figures, and returns a renderable specification with source citations. Every "
        "number is computed from API data; the language model only chooses the analysis."
    ),
    dependencies=[Depends(enforce_rate_limit)],
)
async def visualize(request: Request, payload: VisualizeRequest) -> VisualizeResponse:
    result = await _plan(request, payload)
    executor = PlanExecutor(_client(request), _settings(request).max_studies)
    return await executor.execute(result.plan, payload, extra_warnings=result.warnings)


@router.post(
    "/plan",
    response_model=AnalysisPlan,
    summary="Return the analysis plan without executing it",
    description=(
        "Runs only the planning stage. Useful for inspecting how a question was interpreted, "
        "and for debugging retrieval filters without paying for the data fetch."
    ),
    dependencies=[Depends(enforce_rate_limit)],
)
async def plan_only(request: Request, payload: VisualizeRequest) -> AnalysisPlan:
    result = await _plan(request, payload)
    return result.plan


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    summary="Describe what this service can analyze and render",
)
async def capabilities() -> CapabilitiesResponse:
    analysis_for_type: dict[VisualizationType, list[str]] = {}
    for kind, types in ALLOWED_TYPES.items():
        for viz_type in types:
            analysis_for_type.setdefault(viz_type, []).append(kind)

    return CapabilitiesResponse(
        visualization_types=[
            {
                "type": viz_type,
                "payload": "nodes+edges" if viz_type == "network_graph" else "data",
                "produced_by_analysis": kinds,
            }
            for viz_type, kinds in sorted(analysis_for_type.items())
        ],
        dimensions=[
            {
                "id": d.id,
                "label": d.label,
                "kind": d.kind,
                "multi_valued": d.multi_valued,
                "network_eligible": d.network_eligible,
                "supports_exact_counts": d.supports_exact_counts,
                "source_field": d.source_field,
                "description": d.description,
            }
            for d in DIMENSIONS.values()
        ],
        measures=[
            {"id": m.id, "label": m.label, "unit": m.unit, "description": m.description}
            for m in MEASURES.values()
        ],
        metrics=[
            {"id": m.id, "label": m.label, "unit": m.unit, "description": m.description}
            for m in METRICS.values()
        ],
        filters={
            "phases": list(PHASES),
            "statuses": list(STATUSES),
            "study_types": list(STUDY_TYPES),
            "intervention_types": list(INTERVENTION_TYPES),
            "sponsor_classes": list(SPONSOR_CLASSES),
        },
    )


@router.get("/health", summary="Liveness and configuration check")
async def health(request: Request) -> dict[str, object]:
    settings = _settings(request)
    return {
        "status": "ok",
        "planner_configured": bool(settings.anthropic_api_key),
        "model": settings.model,
        "ctgov_api": settings.ctgov_base_url,
        "cache_enabled": settings.cache_enabled,
    }
