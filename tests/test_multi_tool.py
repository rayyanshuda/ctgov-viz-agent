"""A planner run that chains several probe tools before submitting.

Two versions of the same scenario:

``TestScriptedMultiTool`` (offline, default suite)
    The model is scripted, but the probe tools are the real :class:`ToolExecutor` running
    over the captured myeloma page. This pins down that every tool's output reaches the
    model in order and that the loop still ends in a validated plan.

``TestLiveMultiTool`` (``-m live``)
    The real model and the real ClinicalTrials.gov API, run end to end through the
    executor. Prints the tool trace so the model's reasoning path can be inspected::

        uv run pytest -m live tests/test_multi_tool.py -s
"""

from __future__ import annotations

import json

import pytest

from app.agent.planner import LLMPlanner
from app.agent.tools import ToolExecutor
from app.config import Settings
from app.ctgov.client import CTGovClient, FetchResult
from app.executor import PlanExecutor
from app.models.request import VisualizeRequest
from tests.test_planner import ScriptedModel, tool_use

MULTI_TOOL_QUESTION = (
    "How do Keytruda trials sponsored by Merck break down by phase, "
    "and which conditions do they target most?"
)

MYELOMA_PLAN = {
    "interpretation": "Top conditions studied in multiple myeloma trials.",
    "assumptions": ["Conditions taken from the registry's MeSH terms."],
    "retrieval": {
        "cohorts": [{"name": "Myeloma", "filters": {"conditions": ["multiple myeloma"]}}]
    },
    "analysis": {
        "kind": "group_by",
        "dimension": "condition_mesh",
        "measure": "trial_count",
        "top_k": 8,
    },
    "visualization": {"type": "bar_chart", "title": "Most Studied Conditions in Myeloma Trials"},
}


class FixtureClient:
    """Stands in for CTGovClient, serving the captured myeloma page for every query."""

    def __init__(self, records):
        self.records = records
        self.counted: list = []
        self.fetched: list = []

    async def count(self, filters, extra_advanced=None):
        self.counted.append(filters)
        return len(self.records)

    async def fetch(self, filters, *, fields, max_studies, cohort=""):
        self.fetched.append((filters, tuple(fields)))
        page = self.records[:max_studies]
        return FetchResult(records=page, total_count=len(self.records), truncated=False)


def _tool_results(call: dict) -> list[dict]:
    return [
        block
        for message in call["messages"]
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


class TestScriptedMultiTool:
    @pytest.fixture
    def planner(self, settings, records):
        made = LLMPlanner(settings, FixtureClient(records))
        return made

    async def test_three_probe_tools_then_submit(self, planner):
        planner.client = ScriptedModel(
            [tool_use("resolve_entity", {"kind": "condition", "text": "myeloma"}, "tu_1")],
            [
                tool_use(
                    "preview_result_size",
                    {"filters": {"conditions": ["multiple myeloma"]}},
                    "tu_2",
                )
            ],
            [
                tool_use(
                    "list_dimension_values",
                    {
                        "filters": {"conditions": ["multiple myeloma"]},
                        "dimension": "condition_mesh",
                        "top_n": 5,
                    },
                    "tu_3",
                )
            ],
            [tool_use("submit_plan", MYELOMA_PLAN, "tu_4")],
        )

        result = await planner.plan(
            VisualizeRequest(query="Which conditions do myeloma trials study most?")
        )

        # Every probe ran, in the order the model asked for them.
        assert [c["tool"] for c in result.tool_calls] == [
            "resolve_entity",
            "preview_result_size",
            "list_dimension_values",
        ]
        resolved, preview, values = (c["result"] for c in result.tool_calls)

        assert resolved["matching_trials"] == 120
        assert resolved["normalized_mesh_terms"], "should surface the registry's MeSH terms"
        assert preview["matching_trials"] == 120
        assert "workable" in preview["advice"]
        assert values["dimension"] == "condition_mesh"
        assert 0 < len(values["top_values"]) <= 5
        counts = [v["trials_in_sample"] for v in values["top_values"]]
        assert counts == sorted(counts, reverse=True)

        # Each model turn sees one more tool result than the last: nothing is dropped.
        calls = planner.client.calls
        assert [len(_tool_results(c)) for c in calls] == [0, 1, 2, 3]
        final_results = _tool_results(calls[-1])
        assert [r["tool_use_id"] for r in final_results] == ["tu_1", "tu_2", "tu_3"]
        assert json.loads(final_results[2]["content"])["dimension"] == "condition_mesh"

        assert result.plan.analysis.dimension == "condition_mesh"
        assert result.repair_attempts == 0

    async def test_parallel_tool_calls_in_one_turn_are_all_answered(self, planner):
        planner.client = ScriptedModel(
            [
                tool_use("resolve_entity", {"kind": "drug", "text": "Keytruda"}, "tu_a"),
                tool_use("resolve_entity", {"kind": "sponsor", "text": "Merck"}, "tu_b"),
                tool_use("preview_result_size", {"filters": {"phases": ["PHASE9"]}}, "tu_c"),
            ],
            [tool_use("submit_plan", MYELOMA_PLAN, "tu_d")],
        )

        result = await planner.plan(VisualizeRequest(query=MULTI_TOOL_QUESTION))

        answered = _tool_results(planner.client.calls[1])
        assert [r["tool_use_id"] for r in answered] == ["tu_a", "tu_b", "tu_c"]
        assert "sponsor_names_found" in result.tool_calls[1]["result"]
        # A bad filter comes back as data for the model to learn from, not an exception.
        assert "invalid filters" in result.tool_calls[2]["result"]["error"]
        assert result.plan is not None


@pytest.mark.live
class TestLiveMultiTool:
    async def test_real_model_probes_before_planning(self):
        settings = Settings()
        if not settings.anthropic_api_key:
            pytest.skip("ANTHROPIC_API_KEY not set")

        request = VisualizeRequest(query=MULTI_TOOL_QUESTION)
        async with CTGovClient(settings) as client:
            planning = await LLMPlanner(settings, client).plan(request)
            response = await PlanExecutor(client, settings.max_studies).execute(
                planning.plan, request, extra_warnings=planning.warnings
            )

        print(f"\nQUESTION: {MULTI_TOOL_QUESTION}")
        for i, call in enumerate(planning.tool_calls, 1):
            summary = {
                k: v
                for k, v in call["result"].items()
                if k in {"matching_trials", "sponsor_names_found", "normalized_mesh_terms",
                         "top_values", "advice", "error"}
            }
            print(f"\n[{i}] {call['tool']}({json.dumps(call['input'])})")
            print("    -> " + json.dumps(summary, default=str)[:400])
        print(f"\nPLAN: {planning.plan.model_dump_json(exclude_none=True)}")
        print(f"REPAIRS: {planning.repair_attempts}")
        print(f"\nSTATUS: {response.status}")
        if response.visualization:
            viz = response.visualization
            print(f"CHART: {viz.type} - {viz.title}")
            for row in viz.data[:10]:
                print("   ", {k: v for k, v in row.items() if k != "citations"})

        tools_used = {c["tool"] for c in planning.tool_calls}
        assert len(planning.tool_calls) >= 2, "a brand + sponsor question should be probed"
        assert "resolve_entity" in tools_used
        assert response.status == "ok"
