# The planner agent: generates a validated "AnalysisPlan"

# There are 3 limits to keep this agent from infinitely looping, which at that point it must call "submit_plan":
# Iteration Cap: after "max_tool_iterations", the model is forced to submit the plan, so it stops it from continuously exploring
# Schema Validation: "submit_plan" output is parsed to make sure no dimensions were hallucinated or made-up.
# Repair: any validation errors are handed back as a tool result, so the model can correct its own mistakes. 
#         From testing, majority of the first-attempt failures are just typos in an enum value, and the model
#         can just fix it quickly. If it does reach the "max_repair_attempts" (set in app/config.py), give up, and raise an error.

# Goal: Do not allow any fabricated or hallucinated value to get to the user.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic
from pydantic import ValidationError

from app.agent.prompts import SYSTEM_PROMPT, build_user_message
from app.agent.tools import ToolExecutor, tool_definitions
from app.config import Settings
from app.ctgov.client import CTGovClient
from app.errors import ConfigurationError, PlanningError
from app.models.plan import AnalysisPlan
from app.models.request import VisualizeRequest

logger = logging.getLogger(__name__)

SUBMIT_TOOL = "submit_plan"


@dataclass
class PlanningResult:
    # A validated plan

    plan: AnalysisPlan
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    repair_attempts: int = 0
    warnings: list[str] = field(default_factory=list)


def _submit_tool_definition() -> dict[str, Any]:
    # The plan model itslef is the tool schema

    # From "AnalysisPlan", this means the model sees the structure that is going to be validated
    # This includes the enumerated dimensions and the measures ids, so the schema that is shown, and the schema that is enforced don't differ.

    return {
        "name": SUBMIT_TOOL,
        "description": (
            "Submit the finished analysis plan. Call this once, when you have "
            "decided which trials to retrieve, how to group them, and how to visualize the "
            "result. Do not include any data values, the executor computes those."
        ),
        "input_schema": AnalysisPlan.model_json_schema(),
    }


_WRAPPER_KEYS = ("parameters", "arguments", "input")
# Keys the model
"""Keys the model sometimes wraps tool arguments in.

Observed in roughly a third of runs on some questions: the payload arrives as a correct
plan plus an empty ``"parameters": {}``. That is a tool-calling artifact carrying no
information, but ``extra="forbid"`` rejected it and burned a repair round trip. These are
normalized away *before* validation so the strict schema still guards the fields that
matter — a hallucinated ``"sponsor_country"`` is still an error.
"""


def normalize_tool_arguments(arguments: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    # Return the payload and what was changed
    payload = dict(arguments)
    notes: list[str] = []

    for key in _WRAPPER_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, dict) and not value:
            payload.pop(key)
            notes.append(f"dropped empty {key!r} wrapper")
        elif isinstance(value, dict) and "retrieval" in value and "retrieval" not in payload:
            # The whole plan was nested one level deep.
            payload = dict(value)
            notes.append(f"unwrapped plan nested under {key!r}")
    return payload, notes


def _describe_validation_error(error: ValidationError, payload: dict[str, Any]) -> str:
    # Gives the Pydantic errors back to the model as instructions like feedback; what it should work/act on

    # The model's outputs are also given back with the error (like how a teacher gives back a student's test sheet with their incorrect answer, and telling the student which one is incorrect)
    # Without the model's incorrect output, the model would not know what the mistake was, so it might tend ot make the same mistake on the retry

    lines = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "(root)"
        received = item.get("input")
        shown = repr(received)
        if len(shown) > 160:
            shown = shown[:157] + "…"
        lines.append(
            f"- {location}: {item['msg']} (you sent {type(received).__name__}: {shown})"
        )
    return (
        "The plan did not validate. Fix these problems and call submit_plan again, "
        "sending each field as its proper JSON type (arrays as arrays, not as strings):\n"
        + "\n".join(lines)
    )


class LLMPlanner:
    # Turns natural language question into a validated plan

    def __init__(self, settings: Settings, ctgov_client: CTGovClient) -> None:
        if not settings.anthropic_api_key:
            raise ConfigurationError(
                "ANTHROPIC_API_KEY is not set, so questions cannot be planned.",
                remedy=(
                    "Add ANTHROPIC_API_KEY=sk-ant-... to a .env file in the project root, or "
                    "export it in the environment, then restart the service. See .env.example."
                ),
            )
        self.settings = settings
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.tools = ToolExecutor(ctgov_client)

    async def plan(self, request: VisualizeRequest) -> PlanningResult:
        # Run the loop until a valid plan is produced, or reaches the retry limit

        tools = [*tool_definitions(), _submit_tool_definition()]
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": build_user_message(request.query, request.structured_filters()),
            }
        ]

        result = PlanningResult(plan=None)  # type: ignore[arg-type]
        tool_calls: list[dict[str, Any]] = []
        repairs = 0

        for iteration in range(self.settings.max_tool_iterations):
            is_last = iteration == self.settings.max_tool_iterations - 1
            response = await self._call_model(messages, tools, force_submit=is_last)

            blocks = [b for b in response.content if b.type == "tool_use"]
            if not blocks:
                # The model replied with prose instead of calling a tool. Just tell it to submit_plan with plan now
                # If the model is on the final tool_choice iteration, it will terminate.
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": "Call submit_plan with your plan now.",
                    }
                )
                continue

            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []

            for block in blocks:
                # Tool input is JSON the SDK has already parsed; never string-match on it.
                arguments: dict[str, Any] = dict(block.input)  # type: ignore[arg-type]

                if block.name == SUBMIT_TOOL:
                    payload, notes = normalize_tool_arguments(arguments)
                    if notes:
                        logger.info("Normalized submit_plan arguments: %s", "; ".join(notes))
                    try:
                        plan = AnalysisPlan.model_validate(payload)
                    except ValidationError as exc:
                        repairs += 1
                        logger.info("Plan validation failed (repair %s): %s", repairs, exc)
                        if repairs > self.settings.max_repair_attempts:
                            raise PlanningError(
                                "The planner could not produce a schema-valid plan after "
                                f"{repairs} attempts. Last errors: {_describe_validation_error(exc, payload)}"
                            ) from exc
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": _describe_validation_error(exc, payload),
                            }
                        )
                        continue

                    result.plan = plan
                    result.tool_calls = tool_calls
                    result.repair_attempts = repairs
                    if repairs:
                        result.warnings.append(
                            f"The initial plan failed schema validation and was corrected "
                            f"after {repairs} attempt(s)."
                        )
                    return result

                payload = await self.tools.run(block.name, arguments)
                tool_calls.append({"tool": block.name, "input": arguments, "result": payload})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(payload, default=str),
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        raise PlanningError(
            "The planner did not submit a plan within "
            f"{self.settings.max_tool_iterations} steps."
        )

    async def _call_model(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], force_submit: bool
    ) -> anthropic.types.Message:
        # One messages API call, with errors translated to exceptions
        try:
            return await self.client.messages.create(
                model=self.settings.model,
                max_tokens=self.settings.max_plan_tokens,
                system=SYSTEM_PROMPT,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                tool_choice=(
                    {"type": "tool", "name": SUBMIT_TOOL}
                    if force_submit
                    else {"type": "auto"}
                ),
            )
        except anthropic.AuthenticationError as exc:
            raise ConfigurationError(
                # If the Anthropic API rejected the configured key
                "The Anthropic API rejected the configured key.",
                remedy="Check ANTHROPIC_API_KEY in your .env file.",
            ) from exc
        except anthropic.RateLimitError as exc:
            raise PlanningError(
                # If rate limited by the Anthropic API while planning
                "Rate limited by the Anthropic API while planning.",
                remedy="Wait a moment and retry.",
            ) from exc
        except anthropic.APIStatusError as exc:
            raise PlanningError(
                f"The Anthropic API returned HTTP {exc.status_code} while planning: "
                f"{str(exc)[:200]}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise PlanningError(
                # connection error: couldn't reach the Anthropic API
                "Could not reach the Anthropic API.",
                remedy="Check network connectivity and retry.",
            ) from exc
