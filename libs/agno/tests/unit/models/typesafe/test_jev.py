"""Tests for the Jev model. The TypeSafe client is mocked; nothing here reaches the network."""

import json
import os
from dataclasses import dataclass
from enum import IntEnum
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, Iterator, List, Literal, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

pytest.importorskip("typesafe_sdk")

from agno.agent import Agent  # noqa: E402
from agno.exceptions import ModelProviderError  # noqa: E402
from agno.models.base import Model  # noqa: E402
from agno.models.message import Message  # noqa: E402
from agno.models.response import ModelResponse  # noqa: E402
from agno.models.typesafe import Jev  # noqa: E402
from agno.models.utils import get_model  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.team import Team, TeamMode  # noqa: E402
from agno.utils.typesafe import NONE_OPTION, ROUTE_QUESTION_ID, TOOL_QUESTION_ID  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _system_one_response(answers: Dict[str, Dict[str, Any]], input_tokens: int = 120, output_tokens: int = 8):
    return SimpleNamespace(
        answers=answers,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        model="jev-1.13.0",
        request_id="req_123",
    )


def _jev(answers: Optional[Dict[str, Dict[str, Any]]] = None, **kwargs) -> Jev:
    """A Jev whose sync and async clients return `answers`."""
    response = _system_one_response(answers or {})
    client = MagicMock()
    client.system_one.return_value = response
    async_client = MagicMock()
    async_client.system_one = AsyncMock(return_value=response)
    return Jev(api_key="test-key", client=client, async_client=async_client, **kwargs)


@dataclass
class EchoModel(Model):
    """A stand-in generative model for team members: replies with a fixed line."""

    id: str = "echo"
    name: str = "Echo"
    provider: str = "Test"
    reply: str = "echo"

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(role="assistant", content=self.reply)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(role="assistant", content=self.reply)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield ModelResponse(role="assistant", content=self.reply)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield ModelResponse(role="assistant", content=self.reply)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _support_team(leader: Jev, mode: TeamMode = TeamMode.route, **kwargs) -> Team:
    billing = Agent(name="Billing", id="billing", role="Charges and refunds", model=EchoModel(reply="BILLING REPLY"))
    tech = Agent(name="Tech", id="tech", role="Bugs and outages", model=EchoModel(reply="TECH REPLY"))
    return Team(
        name="Support",
        mode=mode,
        model=leader,
        members=[billing, tech],
        instructions=["Anything about money goes to billing."],
        telemetry=False,
        **kwargs,
    )


def _user(text: str) -> List[Message]:
    return [Message(role="user", content=text)]


class Triage(BaseModel):
    department: Literal["billing", "technical"] = Field(description="Which team should handle this?")
    is_urgent: bool = Field(description="Does the message convey urgency?")


TRIAGE_ANSWERS = {
    "department": {"type": "choice", "choice": "billing", "probabilities": {"billing": 0.9}, "confidence": 0.85},
    "is_urgent": {"type": "noul", "noul": 0.95},
}


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def test_defaults_and_string_resolution():
    model = Jev()
    assert (model.id, model.name, model.provider) == ("jev-latest", "Jev", "TypeSafe")
    assert model.supports_native_structured_outputs is True

    resolved = get_model("typesafe:jev-1.13.0")
    assert isinstance(resolved, Jev) and resolved.id == "jev-1.13.0"


def test_missing_api_key_is_an_authentication_error():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ModelProviderError) as error:
            Jev().get_client()
    assert error.value.status_code == 401
    assert "TYPESAFE_API_KEY" in error.value.message


def test_client_params():
    with patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-key"}):
        params = Jev(id="jev-1.13.0", base_url="https://example.test", timeout=3.0, max_retries=0)._get_client_params()
    assert params["api_key"] == "env-key"
    assert params["model"] == "jev-1.13.0"
    assert params["base_url"] == "https://example.test"
    assert params["timeout"] == 3.0
    assert params["retry"].max_retries == 0


# ---------------------------------------------------------------------------
# output_schema and raw questions
# ---------------------------------------------------------------------------


def test_output_schema_is_filled_and_returned_as_the_model():
    model = _jev(TRIAGE_ANSWERS)
    agent = Agent(
        model=model, output_schema=Triage, instructions="Refunds are allowed within 30 days.", telemetry=False
    )

    run = agent.run("I was charged twice, fix this today!")

    assert run.content == Triage(department="billing", is_urgent=True)
    state, questions = model.client.system_one.call_args.args
    assert state["request"] == "I was charged twice, fix this today!"
    # What the developer told the agent rides along as context
    assert "Refunds are allowed within 30 days." in state["context"]
    assert questions["department"]["type"] == "choice"
    assert questions["is_urgent"]["type"] == "noul"
    # Everything Jev decided stays inspectable
    assert run.model_provider_data["mode"] == "schema"
    assert run.model_provider_data["answers"]["is_urgent"]["noul"] == 0.95
    assert run.model_provider_data["confidence"] == 0.85
    assert run.model_provider_data["model"] == "jev-1.13.0"
    assert run.metrics.input_tokens == 120
    assert run.metrics.output_tokens == 8


@pytest.mark.asyncio
async def test_output_schema_async():
    model = _jev(TRIAGE_ANSWERS)
    run = await Agent(model=model, output_schema=Triage, telemetry=False).arun("I was charged twice")
    assert run.content == Triage(department="billing", is_urgent=True)
    model.async_client.system_one.assert_awaited_once()


def test_output_schema_streaming_yields_one_chunk():
    model = _jev(TRIAGE_ANSWERS)
    agent = Agent(model=model, output_schema=Triage, telemetry=False)
    chunks = [event for event in agent.run("I was charged twice", stream=True) if getattr(event, "content", None)]
    assert len(chunks) >= 1
    assert model.client.system_one.call_count == 1


def test_score_field_is_decoded_to_the_enum_member():
    class Severity(IntEnum):
        low = 0
        high = 1

    class Report(BaseModel):
        severity: Severity = Field(description="How severe is the bug?")

    model = _jev({"severity": {"type": "score", "score": 0.8, "confidence": 0.7}})
    run = Agent(model=model, output_schema=Report, telemetry=False).run("The app wipes my data on every launch")
    assert run.content.severity is Severity.high


def test_raw_questions_return_the_answers_as_json():
    answers = {"spam": {"type": "noul", "noul": 0.02}}
    model = _jev(answers, questions={"spam": {"type": "noul", "instructions": "Is this message spam?"}})

    run = Agent(model=model, telemetry=False).run("Lunch at noon?")

    assert json.loads(run.content) == answers
    assert model.client.system_one.call_args.args[1] == {
        "spam": {"type": "noul", "instructions": "Is this message spam?"}
    }
    assert run.model_provider_data["mode"] == "questions"


def test_questions_and_output_schema_together_are_rejected():
    model = _jev(questions={"spam": {"type": "noul", "instructions": "Spam?"}})
    with pytest.raises(ModelProviderError, match="both `questions` and an output_schema") as error:
        model.invoke(messages=_user("hi"), assistant_message=Message(role="assistant"), response_format=Triage)
    assert error.value.status_code == 400
    model.client.system_one.assert_not_called()


def test_json_mode_is_rejected():
    model = _jev()
    with pytest.raises(ModelProviderError, match="output_schema class itself"):
        model.invoke(
            messages=_user("hi"), assistant_message=Message(role="assistant"), response_format={"type": "json_object"}
        )


def test_plain_text_generation_is_rejected_with_guidance():
    run = Agent(model=_jev(), telemetry=False).run("Write me a poem")
    assert run.status == RunStatus.error
    assert "Jev cannot generate text" in run.content
    assert "need their own generative model" in run.content


# ---------------------------------------------------------------------------
# Team leader
# ---------------------------------------------------------------------------


def _route_answer(member_id: str, confidence: float = 0.9) -> Dict[str, Dict[str, Any]]:
    return {ROUTE_QUESTION_ID: {"type": "choice", "choice": member_id, "probabilities": {}, "confidence": confidence}}


def test_route_returns_the_member_reply_after_one_jev_call():
    leader = _jev(_route_answer("tech"))
    run = _support_team(leader).run("The app crashes on login")

    # The member's reply is the answer, with nothing from the leader in front of it
    assert run.content == "TECH REPLY"
    assert leader.client.system_one.call_count == 1

    state, questions = leader.client.system_one.call_args.args
    # The roster travels as choice options, not as state
    assert state == {"request": "The app crashes on login"}
    route = questions[ROUTE_QUESTION_ID]
    assert list(route["criteria"]) == ["billing", "tech"]
    assert route["criteria"]["tech"] == {"name": "Tech", "role": "Bugs and outages"}
    assert "Anything about money goes to billing." in route["instructions"]["guidance"]


def test_route_hands_the_request_over_verbatim():
    leader = _jev(_route_answer("billing"))
    response = leader.invoke(
        messages=[
            Message(role="system", content=_leader_prompt(_support_team(leader))),
            Message(role="user", content="Refund order A-104, please."),
        ],
        assistant_message=Message(role="assistant"),
        tools=[{"type": "function", "function": {"name": "delegate_task_to_member"}}],
    )
    assert response.content is None
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]["function"]
    assert call["name"] == "delegate_task_to_member"
    assert json.loads(call["arguments"]) == {"member_id": "billing", "task": "Refund order A-104, please."}
    assert response.provider_data["selected"] == "billing"


def _leader_prompt(team: Team) -> str:
    from agno.run.base import RunContext
    from agno.session.team import TeamSession

    team.initialize_team()
    message = team.get_system_message(
        session=TeamSession(session_id="s"), run_context=RunContext(run_id="r", session_id="s")
    )
    assert message is not None
    return str(message.content)


@pytest.mark.asyncio
async def test_route_async():
    leader = _jev(_route_answer("billing"))
    run = await _support_team(leader).arun("I was charged twice")
    assert run.content == "BILLING REPLY"
    leader.async_client.system_one.assert_awaited_once()


def test_route_streaming():
    leader = _jev(_route_answer("billing"))
    events = list(_support_team(leader).run("I was charged twice", stream=True))
    assert "BILLING REPLY" in "".join(str(getattr(e, "content", "") or "") for e in events)
    assert leader.client.system_one.call_count == 1


def test_route_low_confidence_uses_the_fallback_member():
    leader = _jev(_route_answer("tech", confidence=0.3), min_confidence=0.6, fallback_member="Billing")
    run = _support_team(leader).run("hmm")
    assert run.content == "BILLING REPLY"


def test_route_low_confidence_without_fallback_hands_over_to_fallback_models():
    leader = _jev(_route_answer("tech", confidence=0.3), min_confidence=0.6)

    with pytest.raises(ModelProviderError, match="confidence 0.30") as error:
        leader.invoke(
            messages=[
                Message(role="system", content=_leader_prompt(_support_team(leader))),
                Message(role="user", content="hmm"),
            ],
            assistant_message=Message(role="assistant"),
            tools=[{"type": "function", "function": {"name": "delegate_task_to_member"}}],
        )
    # A server-side status, so a generative model in `fallback_models` gets the turn
    assert error.value.status_code == 502


def test_unknown_fallback_member_is_rejected_before_any_call():
    leader = _jev(_route_answer("tech"), fallback_member="nobody")
    run = _support_team(leader).run("hi")
    assert run.status == RunStatus.error
    assert "fallback_member 'nobody' is not on the team" in run.content
    leader.client.system_one.assert_not_called()


@pytest.mark.parametrize("mode", [TeamMode.coordinate, TeamMode.tasks])
def test_teams_jev_cannot_lead_are_rejected(mode):
    leader = _jev(_route_answer("tech"))
    run = _support_team(leader, mode=mode).run("The app crashes on login")
    assert run.status == RunStatus.error
    assert "Jev can only lead route or broadcast teams" in run.content
    leader.client.system_one.assert_not_called()


def test_broadcast_sends_the_request_to_every_member_without_calling_jev():
    leader = _jev()
    run = _support_team(leader, mode=TeamMode.broadcast).run("What went wrong with order A-104?")
    assert "BILLING REPLY" in run.content and "TECH REPLY" in run.content
    leader.client.system_one.assert_not_called()


def test_member_that_inherits_jev_explains_the_problem():
    leader = _jev(_route_answer("billing"))
    team = Team(
        name="Support",
        mode=TeamMode.route,
        model=leader,
        members=[Agent(name="Billing", id="billing", role="Charges"), Agent(name="Tech", id="tech", role="Bugs")],
        telemetry=False,
    )
    run = team.run("I was charged twice")
    assert "need their own generative model" in str(run.content)


# ---------------------------------------------------------------------------
# Closed-set tool calling
# ---------------------------------------------------------------------------


def set_thermostat(mode: Literal["heat", "cool", "off"], eco: bool = False) -> str:
    """Set the thermostat.

    Args:
        mode: the mode to switch to
        eco: whether to save energy
    """
    return f"thermostat set to {mode}, eco={eco}"


def lock_doors() -> str:
    """Lock every door in the house."""
    return "doors locked"


def send_message(text: str) -> str:
    """Send a text message."""
    return text


def test_closed_set_tool_call_runs_the_tool_and_returns_its_result():
    leader = _jev(
        {
            TOOL_QUESTION_ID: {"type": "choice", "choice": "set_thermostat", "confidence": 0.9},
            "set_thermostat.mode": {"type": "choice", "choice": "cool", "confidence": 0.8},
            "set_thermostat.eco": {"type": "noul", "noul": 0.9},
            "set_thermostat.eco?": {"type": "noul", "noul": 0.2},
        }
    )
    run = Agent(model=leader, tools=[set_thermostat, lock_doors], telemetry=False).run("It is boiling in here")

    # eco was not stated, so the function default stands; the tool result is the answer
    assert run.content == "thermostat set to cool, eco=False"
    # One decision, then the result is handed back without asking Jev again
    assert leader.client.system_one.call_count == 1


def test_no_matching_tool_is_a_fallback_able_error():
    leader = _jev({TOOL_QUESTION_ID: {"type": "choice", "choice": NONE_OPTION, "confidence": 0.9}})
    tools = [{"type": "function", "function": {"name": "lock_doors", "description": "Lock every door."}}]
    with pytest.raises(ModelProviderError, match="none of the tools fits the request") as error:
        leader.invoke(messages=_user("Tell me a joke"), assistant_message=Message(role="assistant"), tools=tools)
    assert error.value.status_code == 502


def test_tool_with_a_required_free_text_argument_is_rejected():
    leader = _jev()
    run = Agent(model=leader, tools=[send_message], telemetry=False).run("Tell Sam I am late")
    assert run.status == RunStatus.error
    assert "required argument 'text'" in run.content
    leader.client.system_one.assert_not_called()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raised, status_code",
    [
        (type("ApiError", (Exception,), {"status": 422})("bad question"), 422),
        (type("RateLimited", (Exception,), {"status": 429})("slow down"), 429),
        (TimeoutError("timed out"), 504),
        (ConnectionError("no route"), 503),
        (RuntimeError("boom"), 502),
    ],
)
def test_sdk_errors_are_mapped_to_provider_errors(raised, status_code):
    model = _jev(questions={"spam": {"type": "noul", "instructions": "Spam?"}})
    model.client.system_one.side_effect = raised
    with pytest.raises(ModelProviderError) as error:
        model.invoke(messages=_user("hi"), assistant_message=Message(role="assistant"))
    assert error.value.status_code == status_code
    assert error.value.model_id == "jev-latest"
