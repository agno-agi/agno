import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Literal, Optional

import pytest
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import InputCheckError, ModelProviderError
from agno.memory import MemoryManager
from agno.models.base import Model
from agno.models.decision import ChoiceAnswer, DecisionModel, NoulAnswer, Score, ScoreAnswer
from agno.models.openai import OpenAIResponses
from agno.models.response import ModelResponse
from agno.models.typesafe import Jev
from agno.models.utils import get_agent_model, get_model
from agno.run import RunStatus
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunErrorEvent, RunOutput, RunStartedEvent
from agno.team import Team


class Ticket(BaseModel):
    """Triage a support ticket."""

    area: Literal["billing", "technical"] = Field(description="Which team owns it")
    urgent: bool = Field(description="Needs action today")
    severity: Annotated[int, Score(levels=["Low", "High"])] = Field(description="How bad")


RESPONSE = {
    "model": "fake-1",
    "answers": {
        "area": {"type": "choice", "choice": "technical", "probabilities": {"billing": 0.1, "technical": 0.9}},
        "urgent": {"type": "noul", "noul": 0.93},
        "severity": {"type": "score", "score": 0.8, "probabilities": {"0": 0.2, "1": 0.8}, "confidence": 0.6},
    },
    "usage": {"input_tokens": 120, "output_tokens": 0},
}


@dataclass
class FakeDecisionModel(DecisionModel):
    id: str = "fake"
    name: str = "FakeDecisionModel"
    provider: Optional[str] = "Fake"
    response: Dict[str, Any] = field(default_factory=lambda: RESPONSE)
    error: Optional[Exception] = None
    requests: List[Dict[str, Any]] = field(default_factory=list)

    def _request(self, body: Dict[str, Any]) -> Dict[str, Any]:
        self.requests.append(body)
        if self.error is not None:
            raise self.error
        return self.response

    async def _arequest(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(body)


EXPECTED = Ticket(area="technical", urgent=True, severity=1)


def assert_completed(run: RunOutput) -> None:
    assert run.status == RunStatus.completed
    assert run.content == EXPECTED
    assert run.content_type == "Ticket"
    assert run.decisions is not None
    assert run.decisions["urgent"] == NoulAnswer(probability=0.93, value=True)
    assert run.decisions["area"] == ChoiceAnswer(value="technical", probabilities={"billing": 0.1, "technical": 0.9})
    assert isinstance(run.decisions["severity"], ScoreAnswer)
    assert run.metrics is not None and run.metrics.input_tokens == 120


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def test_run_fills_output_schema():
    model = FakeDecisionModel()
    agent = Agent(model=model, output_schema=Ticket)

    run = agent.run("Checkout is down")

    assert_completed(run)
    body = model.requests[0]
    assert body["state"] == "Checkout is down"
    assert set(body["questions"]) == {"area", "urgent", "severity"}
    assert body["questions"]["urgent"]["instructions"] == "Triage a support ticket.\nNeeds action today"
    assert run.messages is not None
    assert [m.role for m in run.messages] == ["user", "assistant"]
    assert run.messages[0].content == "Checkout is down"
    assert json.loads(run.messages[1].content) == EXPECTED.model_dump()
    assert run.model == "fake" and run.model_provider == "Fake"


async def test_arun_fills_output_schema():
    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket)
    assert_completed(await agent.arun("Checkout is down"))


def test_structured_input_becomes_dict_state():
    class TicketInput(BaseModel):
        subject: str
        body: str

    model = FakeDecisionModel()
    agent = Agent(model=model, output_schema=Ticket, input_schema=TicketInput)
    agent.run(TicketInput(subject="Down", body="Checkout fails"))
    assert model.requests[0]["state"] == {"subject": "Down", "body": "Checkout fails"}


def test_per_run_output_schema():
    model = FakeDecisionModel()
    agent = Agent(model=model)
    assert_completed(agent.run("Checkout is down", output_schema=Ticket))


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def test_stream_yields_content_event():
    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket)
    events = list(agent.run("Checkout is down", stream=True))
    assert [type(e) for e in events] == [RunContentEvent]
    assert events[0].content == EXPECTED
    assert events[0].content_type == "Ticket"


def test_stream_events_and_run_output():
    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket)
    events = list(agent.run("Checkout is down", stream=True, stream_events=True, yield_run_output=True))
    assert [type(e) for e in events] == [RunStartedEvent, RunContentEvent, RunCompletedEvent, RunOutput]
    completed = events[2]
    assert completed.decisions is not None and completed.decisions["urgent"].probability == 0.93
    json.dumps(completed.to_dict())
    assert_completed(events[3])


async def test_async_stream_events():
    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket)
    events = [e async for e in agent.arun("Checkout is down", stream=True, stream_events=True)]
    assert [type(e) for e in events] == [RunStartedEvent, RunContentEvent, RunCompletedEvent]


# ---------------------------------------------------------------------------
# Errors and hooks
# ---------------------------------------------------------------------------


def test_provider_error_marks_run_as_error():
    agent = Agent(
        model=FakeDecisionModel(error=ModelProviderError("upstream down", status_code=400)), output_schema=Ticket
    )
    run = agent.run("x")
    assert run.status == RunStatus.error
    assert run.content == "upstream down"


def test_stream_provider_error_yields_error_event():
    agent = Agent(
        model=FakeDecisionModel(error=ModelProviderError("upstream down", status_code=400)), output_schema=Ticket
    )
    events = list(agent.run("x", stream=True))
    assert len(events) == 1 and isinstance(events[0], RunErrorEvent)


def test_agent_retries_decision_errors():
    model = FakeDecisionModel(error=ModelProviderError("flaky", status_code=400))
    agent = Agent(model=model, output_schema=Ticket, retries=1, delay_between_retries=0)
    agent.run("x")
    assert len(model.requests) == 2


def test_pre_hook_guardrail_blocks_run():
    def block(run_input, **kwargs):
        raise InputCheckError("blocked")

    model = FakeDecisionModel()
    agent = Agent(model=model, output_schema=Ticket, pre_hooks=[block])
    run = agent.run("x")
    assert run.status == RunStatus.error
    assert model.requests == []


def test_guardrail_rejection_is_not_retried():
    calls = []

    def block(run_input, **kwargs):
        calls.append(1)
        raise InputCheckError("blocked")

    agent = Agent(
        model=FakeDecisionModel(), output_schema=Ticket, pre_hooks=[block], retries=2, delay_between_retries=0
    )
    agent.run("x")
    assert len(calls) == 1


def test_post_hook_sees_typed_content():
    seen = []

    def record(run_output, **kwargs):
        seen.append((run_output.content, run_output.decisions["urgent"].value))

    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket, post_hooks=[record])
    agent.run("x")
    assert seen == [(EXPECTED, True)]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def lookup(query: str) -> str:
    """Look something up."""
    return query


@pytest.mark.parametrize(
    "settings, message",
    [
        ({"tools": [lookup]}, "`tools`"),
        ({"parser_model": OpenAIResponses(id="gpt-5.6-luna", api_key="k")}, "`parser_model`"),
        ({"reasoning_model": OpenAIResponses(id="gpt-5.6-luna", api_key="k")}, "`reasoning_model`"),
        ({"update_memory_on_run": True}, "`memory_manager` needs its own chat model"),
        ({"followups": True}, "`followup_model` needs its own chat model"),
        ({"enable_session_summaries": True}, "`session_summary_manager` needs its own chat model"),
        ({"introduction": "Hi"}, "`introduction`"),
    ],
)
def test_construction_rejects_chat_only_settings(settings, message):
    with pytest.raises(ValueError, match=message):
        Agent(model=FakeDecisionModel(), output_schema=Ticket, **settings)


def test_side_jobs_with_their_own_model_are_allowed():
    memory = MemoryManager(model=OpenAIResponses(id="gpt-5.6-luna", api_key="k"))
    Agent(model=FakeDecisionModel(), output_schema=Ticket, memory_manager=memory)


def test_run_without_output_schema_raises():
    agent = Agent(model=FakeDecisionModel())
    with pytest.raises(ValueError, match="needs an `output_schema`"):
        agent.run("x")


def test_unsupported_schema_raises_at_construction():
    class Summary(BaseModel):
        text: str

    with pytest.raises(ValueError, match="Summary.text"):
        Agent(model=FakeDecisionModel(), output_schema=Summary)


def test_continue_run_and_background_are_rejected():
    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket)
    with pytest.raises(ValueError, match="cannot be continued"):
        agent.continue_run(run_id="r", session_id="s")


async def test_background_run_is_rejected(tmp_path):
    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket, db=SqliteDb(db_file=str(tmp_path / "bg.db")))
    with pytest.raises(ValueError, match="Background runs"):
        await agent.arun("x", background=True)


# ---------------------------------------------------------------------------
# Storage and model resolution
# ---------------------------------------------------------------------------


def test_run_output_round_trip_keeps_typed_decisions():
    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket)
    run = agent.run("x")
    restored = RunOutput.from_dict(json.loads(json.dumps(run.to_dict())))
    assert restored.decisions == run.decisions
    assert isinstance(restored.decisions["severity"], ScoreAnswer)


def test_session_persists_decision_runs(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "decisions.db"))
    agent = Agent(model=FakeDecisionModel(), output_schema=Ticket, db=db)
    agent.run("first", session_id="s1")
    agent.run("second", session_id="s1")

    session = agent.get_session(session_id="s1")
    assert session is not None and session.runs is not None
    assert len(session.runs) == 2
    assert session.runs[-1].decisions["urgent"].value is True


def test_agent_model_string_resolves_decision_model():
    assert isinstance(get_agent_model("typesafe:jev-latest"), Jev)
    with pytest.raises(ValueError, match="can only be used as an Agent's `model`"):
        get_model("typesafe:jev-latest")


def test_decision_model_is_rejected_in_other_model_slots():
    with pytest.raises(ValueError, match="can only be used as an Agent's `model`"):
        Agent(model=FakeDecisionModel(), output_schema=Ticket, output_model=Jev(api_key="k"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


class _ScriptedLeader(Model):
    """Delegates once to the triage member, then answers."""

    def __init__(self) -> None:
        super().__init__(id="leader", name="leader", provider="test")
        self._turn = 0

    def __deepcopy__(self, memo: dict) -> "_ScriptedLeader":
        return self

    def _next(self) -> ModelResponse:
        self._turn += 1
        if self._turn == 1:
            response = ModelResponse(role="assistant")
            args = json.dumps({"member_id": "triage", "task": "Checkout is down"})
            response.tool_calls = [
                {"id": "call-1", "type": "function", "function": {"name": "delegate_task_to_member", "arguments": args}}
            ]
            return response
        return ModelResponse(content="routed", role="assistant")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def test_decision_agent_as_team_member():
    member = Agent(id="triage", name="Triage", model=FakeDecisionModel(), output_schema=Ticket, telemetry=False)
    team = Team(model=_ScriptedLeader(), members=[member], telemetry=False)

    run = team.run("Route this ticket")

    assert run.member_responses
    member_run = run.member_responses[0]
    assert isinstance(member_run, RunOutput)
    assert member_run.content == EXPECTED
    assert member_run.decisions is not None and member_run.decisions["urgent"].value is True


def test_decision_model_cannot_lead_a_team():
    with pytest.raises(ValueError, match="can only be used as an Agent's `model`"):
        Team(model=Jev(api_key="k"), members=[Agent(model=FakeDecisionModel(), output_schema=Ticket)])


def test_agent_config_stores_decision_model_without_secrets():
    agent = Agent(model=Jev(api_key="secret-key"), output_schema=Ticket)
    config = agent.to_dict()
    assert config["model"] == {"name": "Jev", "id": "jev-latest", "provider": "TypeSafe"}
    assert "secret-key" not in json.dumps(config, default=str)


def test_agent_config_round_trip_rebuilds_decision_model():
    agent = Agent(name="triage", model=Jev(api_key="k"), output_schema=Ticket)
    restored = Agent.from_dict(agent.to_dict())
    assert isinstance(restored.model, Jev)
    assert restored.model.id == "jev-latest"
