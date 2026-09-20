"""Tests for JevTools. The TypeSafe client is mocked; nothing here reaches the network."""

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, Iterator, List, Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools.typesafe import JEV_INSTRUCTIONS, JevQuestion, JevTools


class Review(BaseModel):
    sentiment: Literal["positive", "negative"] = Field(description="Is the review positive or negative?")
    mentions_price: bool = Field(description="Does the review mention the price?")


REVIEW_ANSWERS = {
    "sentiment": {"type": "choice", "choice": "negative", "probabilities": {"negative": 0.9}, "confidence": 0.8},
    "mentions_price": {"type": "noul", "noul": 0.92},
}


def _tools(answers: Dict[str, Dict[str, Any]], **kwargs) -> JevTools:
    tools = JevTools(api_key="test-key", **kwargs)
    response = SimpleNamespace(answers=answers)
    tools.client = MagicMock()
    tools.client.system_one.return_value = response
    tools.async_client = MagicMock()
    tools.async_client.system_one = AsyncMock(return_value=response)
    return tools


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registers_ask_jev_with_an_async_twin():
    tools = JevTools(api_key="k")
    assert tools.name == "jev_tools"
    assert set(tools.functions) == {"ask_jev"}
    assert set(tools.async_functions) == {"ask_jev"}
    # The toolkit's own id is not the Jev model id
    assert tools.model == "jev-latest"


def test_evaluate_is_registered_only_with_fixed_questions():
    assert set(JevTools(api_key="k", output_schema=Review).functions) == {"evaluate", "ask_jev"}
    raw = JevTools(api_key="k", questions={"spam": {"type": "noul", "instructions": "Is this spam?"}})
    assert set(raw.async_functions) == {"evaluate", "ask_jev"}


def test_flags_gate_registration():
    tools = JevTools(api_key="k", output_schema=Review, enable_ask_jev=False)
    assert set(tools.functions) == {"evaluate"}
    assert set(JevTools(api_key="k", enable_ask_jev=False).functions) == set()


def test_schema_and_questions_together_are_rejected():
    with pytest.raises(ValueError, match="not both"):
        JevTools(api_key="k", output_schema=Review, questions={"x": {"type": "noul", "instructions": "x?"}})


def test_reads_the_api_key_from_the_environment():
    with patch.dict("os.environ", {"TYPESAFE_API_KEY": "env-key"}):
        assert JevTools().api_key == "env-key"


def test_teaches_the_agent_how_to_write_questions():
    tools = JevTools(api_key="k")
    assert tools.instructions == JEV_INSTRUCTIONS
    assert tools.add_instructions is True


# ---------------------------------------------------------------------------
# evaluate: fixed questions, the agent supplies the state
# ---------------------------------------------------------------------------


def test_evaluate_fills_the_schema():
    tools = _tools(REVIEW_ANSWERS, output_schema=Review)
    result = json.loads(tools.evaluate("Way too expensive for what it does."))

    assert result["values"] == {"sentiment": "negative", "mentions_price": True}
    assert result["answers"]["mentions_price"]["noul"] == 0.92
    state, questions = tools.client.system_one.call_args.args
    assert state == "Way too expensive for what it does."
    assert set(questions) == {"sentiment", "mentions_price"}


def test_evaluate_sends_json_state_structured():
    tools = _tools(REVIEW_ANSWERS, output_schema=Review)
    tools.evaluate('{"review": "Too expensive.", "product": "Kettle"}')
    assert tools.client.system_one.call_args.args[0] == {"review": "Too expensive.", "product": "Kettle"}


@pytest.mark.asyncio
async def test_evaluate_async_with_raw_questions():
    answers = {"spam": {"type": "noul", "noul": 0.03}}
    tools = _tools(answers, questions={"spam": {"type": "noul", "instructions": "Is this spam?"}})
    assert json.loads(await tools.aevaluate("Lunch at noon?")) == {"answers": answers}
    tools.async_client.system_one.assert_awaited_once()


# ---------------------------------------------------------------------------
# ask_jev: the agent writes the questions
# ---------------------------------------------------------------------------

QUESTIONS = [
    JevQuestion(id="urgent", type="noul", instructions="Does the message convey urgency?", options=[]),
    JevQuestion(id="team", type="choice", instructions="Which team handles this?", options=["billing", "tech", "none"]),
    JevQuestion(
        id="anger", type="score", instructions="How angry is the customer?", options=["calm", "annoyed", "furious"]
    ),
]


def test_ask_jev_builds_typed_questions():
    tools = _tools({"urgent": {"type": "noul", "noul": 0.9}})
    result = json.loads(tools.ask_jev("My payouts have failed for 3 days!", QUESTIONS))

    assert result == {"answers": {"urgent": {"type": "noul", "noul": 0.9}}}
    questions = tools.client.system_one.call_args.args[1]
    assert questions["urgent"] == {"type": "noul", "instructions": "Does the message convey urgency?"}
    assert questions["team"]["criteria"] == {"billing": None, "tech": None, "none": None}
    assert questions["anger"]["criteria"] == ["calm", "annoyed", "furious"]


@pytest.mark.asyncio
async def test_ask_jev_async():
    tools = _tools({"urgent": {"type": "noul", "noul": 0.9}})
    result = json.loads(await tools.aask_jev("Help!", QUESTIONS[:1]))
    assert result["answers"]["urgent"]["noul"] == 0.9


def test_bad_questions_come_back_as_an_error_the_agent_can_fix():
    tools = _tools({})
    one_level = [JevQuestion(id="anger", type="score", instructions="How angry?", options=["calm"])]
    assert "2 to 10 levels" in json.loads(tools.ask_jev("x", one_level))["error"]
    assert "at least one question" in json.loads(tools.ask_jev("x", []))["error"]
    tools.client.system_one.assert_not_called()


def test_api_failures_come_back_as_an_error():
    tools = _tools({})
    tools.client.system_one.side_effect = ConnectionError("no route")
    assert json.loads(tools.ask_jev("x", QUESTIONS[:1])) == {"error": "no route"}


# ---------------------------------------------------------------------------
# Through a real Agent: schema generation and argument coercion
# ---------------------------------------------------------------------------


@dataclass
class ScriptedModel(Model):
    """Calls `ask_jev` once with JSON arguments, then answers with whatever the tool returned."""

    id: str = "scripted"
    name: str = "Scripted"
    provider: str = "Test"

    def _respond(self, messages: List[Any]) -> ModelResponse:
        tool_messages = [m for m in messages if m.role == "tool"]
        if tool_messages:
            return ModelResponse(role="assistant", content=str(tool_messages[-1].content))
        arguments = {
            "state": "My payouts have failed for 3 days!",
            "questions": [{"id": "urgent", "type": "noul", "instructions": "Is this urgent?", "options": []}],
        }
        call = {"id": "call_1", "type": "function", "function": {"name": "ask_jev", "arguments": json.dumps(arguments)}}
        return ModelResponse(role="assistant", tool_calls=[call])

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._respond(kwargs["messages"])

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._respond(kwargs["messages"])

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._respond(kwargs["messages"])

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._respond(kwargs["messages"])

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def test_ask_jev_schema_lists_typed_questions():
    function = JevTools(api_key="k").functions["ask_jev"]
    # The schema is derived when an agent prepares the tool, not at registration
    function.process_entrypoint(strict=False)
    question = function.to_dict()["parameters"]["properties"]["questions"]["items"]
    assert set(question["properties"]) == {"id", "type", "instructions", "options"}
    assert question["properties"]["type"]["enum"] == ["noul", "choice", "score"]
    # Every field is required, which strict function schemas insist on
    assert set(question["required"]) == {"id", "type", "instructions", "options"}


def test_agent_calls_ask_jev_with_json_arguments():
    tools = _tools({"urgent": {"type": "noul", "noul": 0.9}})
    run = Agent(model=ScriptedModel(), tools=[tools], telemetry=False).run("Is this ticket urgent?")

    assert json.loads(run.content) == {"answers": {"urgent": {"type": "noul", "noul": 0.9}}}
    assert tools.client.system_one.call_args.args[1] == {"urgent": {"type": "noul", "instructions": "Is this urgent?"}}


@pytest.mark.asyncio
async def test_agent_calls_the_async_twin():
    tools = _tools({"urgent": {"type": "noul", "noul": 0.9}})
    run = await Agent(model=ScriptedModel(), tools=[tools], telemetry=False).arun("Is this ticket urgent?")

    assert json.loads(run.content)["answers"]["urgent"]["noul"] == 0.9
    tools.async_client.system_one.assert_awaited_once()
    tools.client.system_one.assert_not_called()
