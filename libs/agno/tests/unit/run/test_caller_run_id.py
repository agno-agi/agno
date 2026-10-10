"""caller_run_id records the run that started this one from outside it.

A run dispatched by another run (StudioRunnerTools, or any caller threading its
own run id) lives in its own session and stays a top-level run there. It must
not reuse parent_run_id: history reads drop runs with parent_run_id set, so the
dispatched component would lose its own conversation on the next turn.
"""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.team import Team
from agno.workflow import Workflow
from agno.workflow.agent import WorkflowAgent
from agno.workflow.types import StepInput, StepOutput


class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="ok",
            role="assistant",
            response_usage=MessageMetrics(),
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "caller_run_id.db"))


def _agent(db) -> Agent:
    return Agent(id="callee", model=MockModel(), db=db, add_history_to_context=True, telemetry=False)


def _team(db) -> Team:
    member = Agent(id="member", model=MockModel(), telemetry=False)
    return Team(id="callee-team", model=MockModel(), members=[member], db=db, telemetry=False)


def _echo(step_input: StepInput) -> StepOutput:
    return StepOutput(content=f"echo: {step_input.input}")


def _workflow(db) -> Workflow:
    return Workflow(id="callee-wf", steps=[_echo], db=db, telemetry=False)


def _workflow_with_agent(db) -> Workflow:
    # MockModel answers without calling run_workflow, so this exercises the
    # workflow agent's direct-reply path.
    return Workflow(id="callee-wf-agent", steps=[_echo], db=db, agent=WorkflowAgent(model=MockModel()), telemetry=False)


class TestRunOutputField:
    @pytest.mark.parametrize("cls", [RunOutput, TeamRunOutput, WorkflowRunOutput])
    def test_round_trips_through_dict(self, cls):
        restored = cls.from_dict(cls(run_id="r", caller_run_id="caller").to_dict())
        assert restored.caller_run_id == "caller"
        assert restored.parent_run_id is None

    @pytest.mark.parametrize("cls", [RunOutput, TeamRunOutput, WorkflowRunOutput])
    def test_defaults_to_none(self, cls):
        assert cls(run_id="r").caller_run_id is None
        assert "caller_run_id" not in cls(run_id="r").to_dict()


class TestAgent:
    def test_run_records_and_persists_caller(self, db):
        agent = _agent(db)
        out = agent.run("hi", session_id="s", caller_run_id="caller-1")
        assert out.caller_run_id == "caller-1"
        assert out.parent_run_id is None
        stored = agent.get_run_output(run_id=out.run_id, session_id="s")
        assert stored is not None and stored.caller_run_id == "caller-1"

    def test_omitted_caller_leaves_field_empty(self, db):
        out = _agent(db).run("hi", session_id="s")
        assert out.caller_run_id is None

    def test_dispatched_run_stays_in_its_own_session_history(self, db):
        agent = _agent(db)
        agent.run("first", session_id="s", caller_run_id="caller-1")
        agent.run("second", session_id="s", caller_run_id="caller-2")
        history = agent.get_session_messages(session_id="s")
        assert [m.content for m in history if m.role == "user"] == ["first", "second"]

    async def test_arun_records_and_persists_caller(self, db):
        agent = _agent(db)
        out = await agent.arun("hi", session_id="s", caller_run_id="caller-1")
        assert out.caller_run_id == "caller-1"
        stored = agent.get_run_output(run_id=out.run_id, session_id="s")
        assert stored is not None and stored.caller_run_id == "caller-1"

    def test_streamed_run_records_caller(self, db):
        agent = _agent(db)
        final = None
        for event in agent.run("hi", session_id="s", caller_run_id="caller-1", stream=True, yield_run_output=True):
            if isinstance(event, RunOutput):
                final = event
        assert final is not None and final.caller_run_id == "caller-1"


class TestTeam:
    def test_run_records_and_persists_caller(self, db):
        team = _team(db)
        out = team.run("hi", session_id="s", caller_run_id="caller-1")
        assert out.caller_run_id == "caller-1"
        assert out.parent_run_id is None
        stored = team.get_run_output(run_id=out.run_id, session_id="s")
        assert stored is not None and stored.caller_run_id == "caller-1"

    async def test_arun_records_and_persists_caller(self, db):
        team = _team(db)
        out = await team.arun("hi", session_id="s", caller_run_id="caller-1")
        assert out.caller_run_id == "caller-1"
        stored = team.get_run_output(run_id=out.run_id, session_id="s")
        assert stored is not None and stored.caller_run_id == "caller-1"


class TestWorkflow:
    def test_run_records_and_persists_caller(self, db):
        wf = _workflow(db)
        out = wf.run("hi", session_id="s", caller_run_id="caller-1")
        assert out.caller_run_id == "caller-1"
        assert out.parent_run_id is None
        stored = wf.get_run_output(run_id=out.run_id, session_id="s")
        assert stored is not None and stored.caller_run_id == "caller-1"

    async def test_arun_records_and_persists_caller(self, db):
        wf = _workflow(db)
        out = await wf.arun("hi", session_id="s", caller_run_id="caller-1")
        assert out.caller_run_id == "caller-1"
        stored = wf.get_run_output(run_id=out.run_id, session_id="s")
        assert stored is not None and stored.caller_run_id == "caller-1"

    def test_workflow_agent_direct_reply_records_caller(self, db):
        wf = _workflow_with_agent(db)
        out = wf.run("hi", session_id="s", caller_run_id="caller-1")
        assert out.caller_run_id == "caller-1"
        stored = wf.get_run_output(run_id=out.run_id, session_id="s")
        assert stored is not None and stored.caller_run_id == "caller-1"

    async def test_async_workflow_agent_direct_reply_records_caller(self, db):
        wf = _workflow_with_agent(db)
        out = await wf.arun("hi", session_id="s", caller_run_id="caller-1")
        assert out.caller_run_id == "caller-1"
        stored = wf.get_run_output(run_id=out.run_id, session_id="s")
        assert stored is not None and stored.caller_run_id == "caller-1"
