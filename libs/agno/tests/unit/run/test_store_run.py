"""``store_run=False`` runs an agent, team or workflow without writing the run or its session.

The run still reads the existing session (history, state) but works on a private copy:
nothing is written back, and a cached session is not changed by the temporary run.
"""

import json
from typing import Any, Dict, List, Optional

import pytest

from agno.agent.agent import Agent
from agno.approval import approval
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media.storage.local import LocalMediaStorage
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.offload import ResultStore
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession
from agno.team.team import Team
from agno.tools import tool
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow


class RecordingModel(Model):
    """A model that answers without a provider call and records the messages it was given."""

    def __init__(self, reply: str = "an answer"):
        super().__init__(id="recording", name="recording", provider="test")
        self._reply = reply
        self.calls: List[List[Any]] = []

    def _resp(self, **kwargs) -> ModelResponse:
        self.calls.append(list(kwargs.get("messages") or []))
        return ModelResponse(content=self._reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs):
        return self._resp(**kwargs)

    async def ainvoke(self, *args, **kwargs):
        return self._resp(**kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self._resp(**kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._resp(**kwargs)

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class ToolCallingModel(Model):
    """A model that calls one tool until a tool result is in the conversation, then answers."""

    def __init__(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None):
        super().__init__(id="tool-calling", name="tool-calling", provider="test")
        self._called_tool = tool_name
        self._arguments = arguments
        self._calls = 0

    def _tool_arguments(self, messages: List[Any]) -> Dict[str, Any]:
        return self._arguments or {}

    def _resp(self, **kwargs) -> ModelResponse:
        self._calls += 1
        messages = list(kwargs.get("messages") or [])
        if not any(getattr(m, "role", None) == "tool" for m in messages):
            call = {
                "id": f"call-{self._calls}",
                "type": "function",
                "function": {"name": self._called_tool, "arguments": json.dumps(self._tool_arguments(messages))},
            }
            return ModelResponse(role="assistant", tool_calls=[call], response_usage=MessageMetrics())
        return ModelResponse(content="team answer", role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs):
        return self._resp(**kwargs)

    async def ainvoke(self, *args, **kwargs):
        return self._resp(**kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self._resp(**kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._resp(**kwargs)

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class DelegatingModel(ToolCallingModel):
    """A team model that delegates the latest user message to one member, then answers."""

    def __init__(self, member_id: str):
        super().__init__("delegate_task_to_member")
        self._member_id = member_id

    def _tool_arguments(self, messages: List[Any]) -> Dict[str, Any]:
        return {"member_id": self._member_id, "task": _user_contents(messages)[-1]}


@pytest.fixture()
def db(tmp_path) -> SqliteDb:
    return SqliteDb(db_file=str(tmp_path / "store_run.db"))


def _approvals(db: SqliteDb) -> int:
    approvals = db.get_approvals()
    rows = approvals[0] if isinstance(approvals, tuple) else approvals
    return len(rows)


@approval
@tool()
def needs_ok(city: str) -> str:
    """Return the weather for a city once a human has approved the call."""
    return f"sunny in {city}"


def _runs(db: SqliteDb, session_id: str) -> int:
    runs = db.get_runs(session_id=session_id)
    assert isinstance(runs, list)
    return len(runs)


def _user_contents(messages: List[Any]) -> List[Optional[str]]:
    return [m.content for m in messages if getattr(m, "role", None) == "user"]


class TestAgent:
    def test_sync_temporary_run_writes_nothing(self, db: SqliteDb):
        agent = Agent(id="a", model=RecordingModel(), db=db)

        output = agent.run("hi", session_id="s1", store_run=False)

        assert output.content == "an answer"
        assert db.get_session(session_id="s1", session_type=SessionType.AGENT) is None
        assert _runs(db, "s1") == 0

        # The default keeps storing.
        agent.run("hi again", session_id="s1")
        assert db.get_session(session_id="s1", session_type=SessionType.AGENT) is not None
        assert _runs(db, "s1") == 1

    @pytest.mark.asyncio
    async def test_async_temporary_run_writes_nothing(self, db: SqliteDb):
        agent = Agent(id="a", model=RecordingModel(), db=db)

        output = await agent.arun("hi", session_id="s1", store_run=False)
        assert output.content == "an answer"

        events = [event async for event in agent.arun("hi", session_id="s1", stream=True, store_run=False)]
        assert events

        assert db.get_session(session_id="s1", session_type=SessionType.AGENT) is None
        assert _runs(db, "s1") == 0

    def test_temporary_run_sees_history_but_does_not_extend_it(self, db: SqliteDb):
        model = RecordingModel()
        agent = Agent(id="a", model=model, db=db, add_history_to_context=True)

        agent.run("first", session_id="s1")
        agent.run("second", session_id="s1", store_run=False)
        agent.run("third", session_id="s1")

        # The temporary run was prompted with the stored history ...
        assert _user_contents(model.calls[1]) == ["first", "second"]
        # ... but the next stored run never saw the temporary one.
        assert _user_contents(model.calls[2]) == ["first", "third"]
        assert _runs(db, "s1") == 2

    def test_cached_session_is_not_changed_by_a_temporary_run(self, db: SqliteDb):
        agent = Agent(id="a", model=RecordingModel(), db=db, cache_session=True)

        agent.run("first", session_id="s1")
        cached = agent._get_cached_session("s1")
        assert cached is not None and len(cached.runs or []) == 1

        agent.run("second", session_id="s1", store_run=False)

        assert agent._get_cached_session("s1") is cached
        assert len(cached.runs or []) == 1
        assert cached.transient is False
        assert _runs(db, "s1") == 1

    def test_introduction_is_not_written_for_a_temporary_run(self, db: SqliteDb):
        agent = Agent(id="a", model=RecordingModel(), db=db, introduction="Hello there")

        agent.run("hi", session_id="s1", store_run=False)

        assert db.get_session(session_id="s1", session_type=SessionType.AGENT) is None
        assert _runs(db, "s1") == 0

    def test_background_rejects_store_run_false(self, db: SqliteDb):
        agent = Agent(id="a", model=RecordingModel(), db=db)

        with pytest.raises(ValueError, match="store_run=False"):
            agent.arun("hi", session_id="s1", background=True, store_run=False)

    def test_paused_temporary_run_creates_no_approval(self, db: SqliteDb):
        model = ToolCallingModel("needs_ok", {"city": "Paris"})
        agent = Agent(id="a", model=model, db=db, tools=[needs_ok])

        output = agent.run("weather?", session_id="s1", store_run=False)

        assert output.is_paused
        assert _approvals(db) == 0
        assert _runs(db, "s1") == 0

        # A stored paused run keeps creating its approval row.
        stored = agent.run("weather?", session_id="s1")
        assert stored.is_paused
        assert _approvals(db) == 1
        assert _runs(db, "s1") == 1

    @pytest.mark.asyncio
    async def test_paused_async_temporary_run_creates_no_approval(self, db: SqliteDb):
        model = ToolCallingModel("needs_ok", {"city": "Paris"})
        agent = Agent(id="a", model=model, db=db, tools=[needs_ok])

        output = await agent.arun("weather?", session_id="s1", store_run=False)
        assert output.is_paused

        events = [event async for event in agent.arun("weather?", session_id="s1", stream=True, store_run=False)]
        assert events

        assert _approvals(db) == 0
        assert _runs(db, "s1") == 0

    def test_media_is_not_offloaded_for_a_temporary_run(self, db: SqliteDb, tmp_path):
        media_root = tmp_path / "media"
        agent = Agent(id="a", model=RecordingModel(), db=db, media_storage=LocalMediaStorage(base_path=str(media_root)))
        image = Image(content=b"png-bytes", id="img-1", mime_type="image/png")

        agent.run("look", session_id="s1", images=[image], store_run=False)
        assert not media_root.exists() or not any(media_root.rglob("*"))

        # A stored run with the same media does offload it.
        agent.run("look", session_id="s1", images=[image])
        assert any(path.is_file() for path in media_root.rglob("*"))

    @pytest.mark.asyncio
    async def test_media_is_not_offloaded_for_an_async_temporary_run(self, db: SqliteDb, tmp_path):
        media_root = tmp_path / "media"
        agent = Agent(id="a", model=RecordingModel(), db=db, media_storage=LocalMediaStorage(base_path=str(media_root)))
        image = Image(content=b"png-bytes", id="img-1", mime_type="image/png")

        await agent.arun("look", session_id="s1", images=[image], store_run=False)
        assert not media_root.exists() or not any(media_root.rglob("*"))

    def test_run_context_carries_the_option(self, db: SqliteDb):
        seen: Dict[str, Any] = {}

        def record(run_context) -> None:
            seen["store_run"] = run_context.store_run

        agent = Agent(id="a", model=RecordingModel(), db=db, pre_hooks=[record])
        agent.run("hi", session_id="s1", store_run=False)
        assert seen["store_run"] is False

        agent.run("hi", session_id="s1")
        assert seen["store_run"] is True


class TestTeam:
    def test_temporary_run_writes_neither_team_nor_member_rows(self, db: SqliteDb):
        model = RecordingModel()
        member = Agent(id="member", name="Member", model=model)
        team = Team(id="t", name="T", model=model, members=[member], db=db)

        output = team.run("hi", session_id="s1", store_run=False)

        assert output.content == "an answer"
        assert db.get_session(session_id="s1", session_type=SessionType.TEAM) is None
        assert _runs(db, "s1") == 0

        team.run("hi", session_id="s1")
        assert db.get_session(session_id="s1", session_type=SessionType.TEAM) is not None
        assert _runs(db, "s1") >= 1

    @pytest.mark.asyncio
    async def test_async_temporary_run_writes_nothing(self, db: SqliteDb):
        model = RecordingModel()
        member = Agent(id="member", name="Member", model=model)
        team = Team(id="t", name="T", model=model, members=[member], db=db)

        output = await team.arun("hi", session_id="s1", store_run=False)
        assert output.content == "an answer"
        assert db.get_session(session_id="s1", session_type=SessionType.TEAM) is None
        assert _runs(db, "s1") == 0

    def test_paused_temporary_team_run_creates_no_approval(self, db: SqliteDb):
        team = Team(
            id="t",
            name="T",
            model=ToolCallingModel("needs_ok", {"city": "Paris"}),
            members=[Agent(id="member", model=RecordingModel())],
            tools=[needs_ok],
            db=db,
        )

        output = team.run("weather?", session_id="s1", store_run=False)

        assert output.is_paused
        assert _approvals(db) == 0
        assert _runs(db, "s1") == 0

        stored = team.run("weather?", session_id="s1")
        assert stored.is_paused
        assert _approvals(db) == 1

    def test_temporary_run_offloads_no_member_messages_to_the_result_store(self, db: SqliteDb):
        member = Agent(id="member", name="Member", model=RecordingModel())
        team = Team(
            id="t",
            name="T",
            model=DelegatingModel("member"),
            members=[member],
            db=db,
            offload_tool_results=ResultStore(threshold_chars=100),
        )
        long_task = "please summarize this " * 20

        team.run(long_task, session_id="s1", store_run=False)

        assert db.get_tool_results_for_session("s1") == []
        assert _runs(db, "s1") == 0

        # A stored run with the same oversized member input does offload it.
        team.run(long_task, session_id="s1")
        assert db.get_tool_results_for_session("s1")

    @pytest.mark.asyncio
    async def test_async_temporary_run_offloads_no_member_messages_to_the_result_store(self, db: SqliteDb):
        member = Agent(id="member", name="Member", model=RecordingModel())
        team = Team(
            id="t",
            name="T",
            model=DelegatingModel("member"),
            members=[member],
            db=db,
            offload_tool_results=ResultStore(threshold_chars=100),
        )

        await team.arun("please summarize this " * 20, session_id="s1", store_run=False)

        assert db.get_tool_results_for_session("s1") == []
        assert _runs(db, "s1") == 0

    def test_member_cached_session_is_not_changed_by_a_temporary_run(self, db: SqliteDb):
        member_model = RecordingModel()
        member = Agent(id="member", name="Member", model=member_model, cache_session=True, add_history_to_context=True)
        team = Team(id="t", name="T", model=DelegatingModel("member"), members=[member], db=db)

        team.run("first", session_id="s1")
        team.run("second", session_id="s1", store_run=False)
        team.run("third", session_id="s1")

        # The member saw the temporary task with its history, but the next delegated run did not.
        assert "first" in _user_contents(member_model.calls[1])
        assert "second" in _user_contents(member_model.calls[1])
        assert "second" not in _user_contents(member_model.calls[2])
        assert "third" in _user_contents(member_model.calls[2])
        cached = member._get_cached_session("s1")
        assert cached is not None and len(cached.runs or []) == 2
        assert _runs(db, "s1") == 4  # two team runs, each with one member run

    def test_background_rejects_store_run_false(self, db: SqliteDb):
        model = RecordingModel()
        team = Team(id="t", name="T", model=model, members=[Agent(id="member", model=model)], db=db)

        with pytest.raises(ValueError, match="store_run=False"):
            team.arun("hi", session_id="s1", background=True, store_run=False)


class TestWorkflow:
    def _workflow(self, db: SqliteDb) -> Workflow:
        step_agent = Agent(id="step-agent", name="StepAgent", model=RecordingModel())
        return Workflow(id="w", name="W", steps=[Step(name="s1", agent=step_agent)], db=db)

    def test_sync_temporary_run_writes_nothing(self, db: SqliteDb):
        workflow = self._workflow(db)

        output = workflow.run("hi", session_id="s1", store_run=False)

        assert output.content == "an answer"
        assert db.get_session(session_id="s1", session_type=SessionType.WORKFLOW) is None
        assert _runs(db, "s1") == 0

        workflow.run("hi", session_id="s1")
        assert db.get_session(session_id="s1", session_type=SessionType.WORKFLOW) is not None
        assert _runs(db, "s1") == 1

    @pytest.mark.asyncio
    async def test_async_temporary_run_writes_nothing(self, db: SqliteDb):
        workflow = self._workflow(db)

        output = await workflow.arun("hi", session_id="s1", store_run=False)
        assert output.content == "an answer"

        events = [event async for event in workflow.arun("hi", session_id="s1", stream=True, store_run=False)]
        assert events

        assert db.get_session(session_id="s1", session_type=SessionType.WORKFLOW) is None
        assert _runs(db, "s1") == 0

    @staticmethod
    def _workflow_agent():
        """A WorkflowAgent whose model call is replaced: it runs the workflow tool once, then answers."""
        from agno.models.openai import OpenAIResponses
        from agno.run.agent import RunOutput
        from agno.run.workflow import WORKFLOW_RUN_OUTPUT_EVENT_TYPES
        from agno.tools.function import FunctionCall
        from agno.workflow.agent import WorkflowAgent

        class ScriptedWorkflowAgent(WorkflowAgent):
            def _events(self):
                call = FunctionCall(function=self.tools[0], arguments={"query": "go"}, call_id="call-1")
                for event in self.model.run_function_call(call, []):
                    if isinstance(event, WORKFLOW_RUN_OUTPUT_EVENT_TYPES):
                        yield event
                yield RunOutput(run_id="agent-response", content="agent answer")

            async def _aevents(self):
                call = FunctionCall(function=self.tools[0], arguments={"query": "go"}, call_id="call-1")
                async for event in self.model.arun_function_calls([call], []):
                    if isinstance(event, WORKFLOW_RUN_OUTPUT_EVENT_TYPES):
                        yield event
                yield RunOutput(run_id="agent-response", content="agent answer")

            def run(self, *args, stream=False, **kwargs):
                if stream:
                    return self._events()
                return list(self._events())[-1]

            def arun(self, *args, stream=False, **kwargs):
                if stream:
                    return self._aevents()

                async def _last():
                    last = None
                    async for event in self._aevents():
                        last = event
                    return last

                return _last()

        return ScriptedWorkflowAgent(model=OpenAIResponses(id="unused"))

    def _agent_workflow(self, db: SqliteDb) -> Workflow:
        def step(step_input) -> StepOutput:
            return StepOutput(content="step done")

        return Workflow(id="w", name="W", agent=self._workflow_agent(), steps=[Step(name="s1", executor=step)], db=db)

    def test_workflow_agent_temporary_run_returns_its_run(self, db: SqliteDb):
        workflow = self._agent_workflow(db)

        output = workflow.run("go", session_id="s1", store_run=False)

        assert output.status == RunStatus.completed
        assert output.workflow_agent_run is not None
        assert db.get_session(session_id="s1", session_type=SessionType.WORKFLOW) is None
        assert _runs(db, "s1") == 0

    @pytest.mark.asyncio
    async def test_workflow_agent_async_temporary_run_returns_its_run(self, db: SqliteDb):
        workflow = self._agent_workflow(db)

        output = await workflow.arun("go", session_id="s1", store_run=False)
        assert output.status == RunStatus.completed
        assert output.workflow_agent_run is not None

        events = [event async for event in workflow.arun("go", session_id="s1", stream=True, store_run=False)]
        assert any(type(event).__name__ == "WorkflowAgentCompletedEvent" for event in events)

        assert db.get_session(session_id="s1", session_type=SessionType.WORKFLOW) is None
        assert _runs(db, "s1") == 0

    def test_nested_workflow_inherits_the_option(self, db: SqliteDb):
        inner_agent = Agent(id="inner-agent", name="InnerAgent", model=RecordingModel())
        inner = Workflow(id="inner", name="Inner", steps=[Step(name="i1", agent=inner_agent)], db=db)
        outer = Workflow(id="outer", name="Outer", steps=[Step(name="o1", workflow=inner)], db=db)

        output = outer.run("hi", session_id="s1", store_run=False)

        assert output.content == "an answer"
        assert db.get_session(session_id="s1", session_type=SessionType.WORKFLOW) is None
        assert _runs(db, "s1") == 0

        outer.run("hi", session_id="s1")
        assert db.get_session(session_id="s1", session_type=SessionType.WORKFLOW) is not None
        assert _runs(db, "s1") >= 1

    @pytest.mark.asyncio
    async def test_nested_workflow_inherits_the_option_async(self, db: SqliteDb):
        inner_agent = Agent(id="inner-agent", name="InnerAgent", model=RecordingModel())
        inner = Workflow(id="inner", name="Inner", steps=[Step(name="i1", agent=inner_agent)], db=db)
        outer = Workflow(id="outer", name="Outer", steps=[Step(name="o1", workflow=inner)], db=db)

        await outer.arun("hi", session_id="s1", store_run=False)
        events = [event async for event in outer.arun("hi", session_id="s1", stream=True, store_run=False)]
        assert events

        assert db.get_session(session_id="s1", session_type=SessionType.WORKFLOW) is None
        assert _runs(db, "s1") == 0

    def test_background_rejects_store_run_false(self, db: SqliteDb):
        workflow = self._workflow(db)

        with pytest.raises(ValueError, match="store_run=False"):
            workflow.arun("hi", session_id="s1", background=True, store_run=False)


class TestTransientMarkerStaysOutOfStorage:
    @pytest.mark.parametrize("session_cls", [AgentSession, TeamSession, WorkflowSession])
    def test_to_dict_omits_the_marker(self, session_cls):
        session = session_cls(session_id="s1")
        session.transient = True

        assert "transient" not in session.to_dict()
        restored = session_cls.from_dict(session.to_dict())
        assert restored is not None and restored.transient is False
