"""The planner loop: tool dispatch, schema enforcement and the repair cycle.

The model is stubbed with scripted responses. That keeps these tests free, offline and
deterministic, and lets us drive the paths that matter — a model that invents a
dimension, one that never submits, one that needs two attempts — which would be
impossible to trigger reliably against a live model.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.planner import LLMPlanner
from app.config import Settings
from app.errors import ConfigurationError, PlanningError
from app.models.plan import AnalysisPlan

VALID_PLAN = {
    "interpretation": "Phase distribution of melanoma trials.",
    "assumptions": ["Interventional trials only."],
    "retrieval": {"cohorts": [{"name": "Melanoma", "filters": {"conditions": ["melanoma"]}}]},
    "analysis": {"kind": "group_by", "dimension": "phase", "measure": "trial_count"},
    "visualization": {"type": "bar_chart", "title": "Melanoma Trials by Phase"},
}


def tool_use(name: str, payload: dict, block_id: str = "tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=payload, id=block_id)


def text(body: str):
    return SimpleNamespace(type="text", text=body)


class ScriptedModel:
    """Returns pre-baked responses in order and records what it was asked."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        # Snapshot the message list: the planner appends to it in place, so storing the
        # reference would make every recorded call show the final state.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if not self._responses:
            raise AssertionError("the planner made more model calls than the script allows")
        blocks = self._responses.pop(0)
        return SimpleNamespace(content=blocks, stop_reason="tool_use")


@pytest.fixture
def planner(settings, monkeypatch):
    class DummyClient:
        pass

    made = LLMPlanner(settings, DummyClient())
    return made


def request(query: str = "How are melanoma trials distributed across phases?", **kwargs):
    from app.models.request import VisualizeRequest

    return VisualizeRequest(query=query, **kwargs)


class TestConfiguration:
    def test_missing_api_key_fails_with_actionable_guidance(self):
        with pytest.raises(ConfigurationError) as exc:
            LLMPlanner(Settings(anthropic_api_key=""), object())
        assert "ANTHROPIC_API_KEY" in exc.value.message
        assert ".env" in exc.value.remedy


class TestHappyPath:
    async def test_single_submit_returns_a_validated_plan(self, planner):
        planner.client = ScriptedModel([tool_use("submit_plan", VALID_PLAN)])
        result = await planner.plan(request())
        assert result.plan.analysis.dimension == "phase"
        assert result.repair_attempts == 0
        assert result.warnings == []

    async def test_structured_filters_are_passed_to_the_model(self, planner):
        planner.client = ScriptedModel([tool_use("submit_plan", VALID_PLAN)])
        await planner.plan(request(drug_name="Pembrolizumab"))
        prompt = planner.client.calls[0]["messages"][0]["content"]
        assert "Pembrolizumab" in prompt
        assert "hard constraints" in prompt


class TestProbeTools:
    async def test_probe_results_are_fed_back_before_submitting(self, planner, monkeypatch):
        async def fake_run(name, arguments):
            return {"matching_trials": 2956, "query": arguments.get("text")}

        monkeypatch.setattr(planner.tools, "run", fake_run)
        planner.client = ScriptedModel(
            [tool_use("resolve_entity", {"kind": "drug", "text": "Keytruda"}, "tu_a")],
            [tool_use("submit_plan", VALID_PLAN, "tu_b")],
        )
        result = await planner.plan(request())

        assert [c["tool"] for c in result.tool_calls] == ["resolve_entity"]
        assert result.tool_calls[0]["result"]["matching_trials"] == 2956
        # Second call must carry the tool result back to the model.
        second = planner.client.calls[1]["messages"]
        tool_results = [
            block
            for message in second
            if isinstance(message.get("content"), list)
            for block in message["content"]
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        assert len(tool_results) == 1
        assert "2956" in tool_results[0]["content"]


class TestRepairLoop:
    async def test_invalid_plan_is_returned_to_the_model_and_corrected(self, planner):
        broken = {**VALID_PLAN, "analysis": {"kind": "group_by", "dimension": "sponsor_country"}}
        planner.client = ScriptedModel(
            [tool_use("submit_plan", broken, "tu_a")],
            [tool_use("submit_plan", VALID_PLAN, "tu_b")],
        )
        result = await planner.plan(request())

        assert result.repair_attempts == 1
        assert result.plan.analysis.dimension == "phase"
        assert "corrected" in result.warnings[0]

    async def test_the_error_message_names_the_offending_field_and_valid_options(self, planner):
        broken = {**VALID_PLAN, "analysis": {"kind": "group_by", "dimension": "sponsor_country"}}
        planner.client = ScriptedModel(
            [tool_use("submit_plan", broken, "tu_a")],
            [tool_use("submit_plan", VALID_PLAN, "tu_b")],
        )
        await planner.plan(request())

        feedback = planner.client.calls[1]["messages"][-1]["content"][0]
        assert feedback["is_error"] is True
        assert "sponsor_country" in feedback["content"]
        assert "lead_sponsor" in feedback["content"], "should list the valid alternatives"

    async def test_gives_up_after_the_repair_budget(self, planner):
        broken = {**VALID_PLAN, "analysis": {"kind": "group_by", "dimension": "nope"}}
        planner.settings = planner.settings.model_copy(update={"max_repair_attempts": 1})
        planner.client = ScriptedModel(
            [tool_use("submit_plan", broken, "a")],
            [tool_use("submit_plan", broken, "b")],
            [tool_use("submit_plan", broken, "c")],
        )
        with pytest.raises(PlanningError, match="schema-valid plan"):
            await planner.plan(request())

    async def test_extra_keys_are_rejected(self, planner):
        broken = {**VALID_PLAN, "invented_field": 42}
        planner.client = ScriptedModel(
            [tool_use("submit_plan", broken, "a")],
            [tool_use("submit_plan", VALID_PLAN, "b")],
        )
        result = await planner.plan(request())
        assert result.repair_attempts == 1


class TestTermination:
    async def test_prose_without_a_tool_call_is_nudged(self, planner):
        planner.client = ScriptedModel(
            [text("Let me think about this.")],
            [tool_use("submit_plan", VALID_PLAN, "tu_b")],
        )
        result = await planner.plan(request())
        assert result.plan is not None

    async def test_never_submitting_fails_rather_than_looping(self, planner):
        planner.settings = planner.settings.model_copy(update={"max_tool_iterations": 3})
        planner.client = ScriptedModel(*[[text("thinking...")] for _ in range(3)])
        with pytest.raises(PlanningError, match="did not submit"):
            await planner.plan(request())

    async def test_final_iteration_forces_the_submit_tool(self, planner):
        planner.settings = planner.settings.model_copy(update={"max_tool_iterations": 2})
        planner.client = ScriptedModel(
            [text("hmm")], [tool_use("submit_plan", VALID_PLAN, "b")]
        )
        await planner.plan(request())
        assert planner.client.calls[0]["tool_choice"] == {"type": "auto"}
        assert planner.client.calls[1]["tool_choice"] == {"type": "tool", "name": "submit_plan"}


class TestToolArgumentNormalization:
    """Transport artifacts must not be mistaken for hallucinated fields.

    The model intermittently decorates its tool arguments — an empty `parameters: {}`
    alongside a perfectly good plan, or the whole plan nested one level deep. Neither
    carries information, but `extra="forbid"` rejected both and burned a repair round
    trip. These are normalized before validation; genuinely invented fields still fail.
    """

    def test_empty_wrapper_key_is_dropped(self):
        from app.agent.planner import normalize_tool_arguments

        payload, notes = normalize_tool_arguments({**VALID_PLAN, "parameters": {}})
        assert "parameters" not in payload
        assert notes and "parameters" in notes[0]
        AnalysisPlan.model_validate(payload)

    def test_plan_nested_under_a_wrapper_is_unwrapped(self):
        from app.agent.planner import normalize_tool_arguments

        payload, notes = normalize_tool_arguments({"parameters": VALID_PLAN})
        assert payload["retrieval"] == VALID_PLAN["retrieval"]
        assert notes and "unwrapped" in notes[0]
        AnalysisPlan.model_validate(payload)

    def test_a_clean_payload_is_untouched(self):
        from app.agent.planner import normalize_tool_arguments

        payload, notes = normalize_tool_arguments(VALID_PLAN)
        assert payload == VALID_PLAN and notes == []

    def test_an_invented_field_still_fails(self):
        from app.agent.planner import normalize_tool_arguments

        payload, _ = normalize_tool_arguments({**VALID_PLAN, "sponsor_country": "US"})
        assert "sponsor_country" in payload, "normalization must not weaken extra='forbid'"
        with pytest.raises(Exception):
            AnalysisPlan.model_validate(payload)

    async def test_spurious_wrapper_no_longer_costs_a_repair(self, planner):
        planner.client = ScriptedModel(
            [tool_use("submit_plan", {**VALID_PLAN, "parameters": {}})]
        )
        result = await planner.plan(request())
        assert result.repair_attempts == 0, "should validate on the first attempt"


class TestRepairMessageQuality:
    async def test_error_shows_what_the_model_actually_sent(self, planner):
        # A wrong type on a nested field, so coercion cannot rescue it.
        broken = {**VALID_PLAN, "analysis": {"kind": "group_by", "dimension": "phase",
                                             "top_k": "not a number"}}
        planner.client = ScriptedModel(
            [tool_use("submit_plan", broken, "a")],
            [tool_use("submit_plan", VALID_PLAN, "b")],
        )
        await planner.plan(request())

        feedback = planner.client.calls[1]["messages"][-1]["content"][0]["content"]
        assert "you sent str" in feedback, "must echo the received type"
        assert "not a number" in feedback, "must echo the received value"
        assert "arrays as arrays" in feedback, "must state the general rule"
