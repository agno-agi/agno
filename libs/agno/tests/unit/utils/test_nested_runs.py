"""Unit tests for agno.utils.nested_runs: runs started inside a tool call of another run."""

import asyncio
import json
import re
from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.utils.nested_runs import NestedRuns, register_nested_run


class MockModel(Model):
    """Minimal offline model: returns a canned text response that used 10 tokens."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="ok",
            role="assistant",
            response_usage=MessageMetrics(input_tokens=6, output_tokens=4, total_tokens=10),
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


def _run(run_id: str, total_tokens: int, status: RunStatus = RunStatus.running) -> RunOutput:
    return RunOutput(
        run_id=run_id, status=status, metrics=RunMetrics(input_tokens=total_tokens, total_tokens=total_tokens)
    )


def test_run_stored_nowhere_adds_its_tokens_to_the_run_whose_tool_started_it():
    outer = _run("outer", 100)
    nested_runs = NestedRuns(outer)
    inner = _run("inner", 30)
    with nested_runs.collect():
        register_nested_run(inner, stored=False)
    # Linked only when the tool call ends, once it is known no team or workflow owns the run
    assert inner.called_from_run_id is None
    inner.status = RunStatus.completed
    nested_runs.add_to_run()

    assert inner.called_from_run_id == "outer"
    assert inner.parent_run_id is None
    assert outer.metrics.total_tokens == 130


def test_stored_run_is_linked_and_keeps_its_tokens():
    outer = _run("outer", 100)
    nested_runs = NestedRuns(outer)
    inner = _run("inner", 30)
    with nested_runs.collect():
        register_nested_run(inner, stored=True)
    inner.status = RunStatus.completed
    nested_runs.add_to_run()

    assert inner.called_from_run_id == "outer"
    assert outer.metrics.total_tokens == 100


def test_run_started_inside_a_nested_runs_own_context_is_not_registered():
    outer = _run("outer", 100)
    nested_runs = NestedRuns(outer)
    root = _run("root", 30)
    step = _run("step", 5)
    with nested_runs.collect():
        own_context = register_nested_run(root, stored=False)
        assert own_context is not None
        with own_context.collect():
            assert register_nested_run(step, stored=False) is None
    root.status = RunStatus.completed
    step.status = RunStatus.completed
    nested_runs.add_to_run()

    assert step.called_from_run_id is None
    assert outer.metrics.total_tokens == 130


async def test_runs_started_in_parallel_in_one_tool_call_are_all_linked():
    outer = _run("outer", 100)
    nested_runs = NestedRuns(outer)
    first = Agent(name="first", model=MockModel(), telemetry=False)
    second = Agent(name="second", model=MockModel(), telemetry=False)

    async def tool_call():
        return await asyncio.gather(first.arun("a"), second.arun("b"))

    first_run, second_run = await nested_runs.acollect(tool_call())
    nested_runs.add_to_run()

    assert first_run.called_from_run_id == "outer"
    assert second_run.called_from_run_id == "outer"
    assert outer.metrics.total_tokens == 120


def test_member_with_a_db_started_inside_a_tool_call_adds_its_tokens(tmp_path):
    outer = _run("outer", 100)
    nested_runs = NestedRuns(outer)
    member = Agent(name="member", model=MockModel(), db=SqliteDb(db_file=str(tmp_path / "member.db")), telemetry=False)
    # Its team saves a member's runs, so one started from a tool is stored nowhere
    member.team_id = "team"

    with nested_runs.collect():
        member_run = member.run("a")
    nested_runs.add_to_run()

    assert member_run.called_from_run_id == "outer"
    assert outer.metrics.total_tokens == 110


def test_run_routes_return_the_run_that_started_a_run():
    from agno.os.schema import RunSchema, TeamRunSchema, WorkflowRunSchema

    assert RunSchema.from_dict({"run_id": "inner", "called_from_run_id": "outer"}).called_from_run_id == "outer"
    assert TeamRunSchema.from_dict({"run_id": "inner", "called_from_run_id": "outer"}).called_from_run_id == "outer"
    assert WorkflowRunSchema.from_dict({"run_id": "inner", "called_from_run_id": "outer"}).called_from_run_id == "outer"


async def test_background_workflow_started_inside_a_tool_call_is_linked(tmp_path):
    from agno.workflow import Workflow
    from agno.workflow.step import Step
    from agno.workflow.types import StepOutput

    outer = _run("outer", 100)
    nested_runs = NestedRuns(outer)
    workflow = Workflow(
        name="workflow",
        db=SqliteDb(db_file=str(tmp_path / "workflow.db")),
        steps=[Step(name="step", executor=lambda step_input: StepOutput(content="ok"))],
    )

    workflow_run = await nested_runs.acollect(workflow.arun("go", session_id="s", background=True))
    for _ in range(100):
        stored_run = await workflow.aget_run(workflow_run.run_id, session_id="s")
        if stored_run is not None and stored_run.status == RunStatus.completed:
            break
        await asyncio.sleep(0.01)

    assert workflow_run.called_from_run_id == "outer"
    assert stored_run.called_from_run_id == "outer"


async def test_closing_an_async_stream_closes_the_stream_it_collects_from():
    closed = []

    async def stream():
        try:
            yield 1
            yield 2
        finally:
            closed.append(True)

    iterator = NestedRuns(None).aiterate(stream())
    await iterator.__anext__()
    await iterator.aclose()

    assert closed == [True]


class ScriptedModel(MockModel):
    """MockModel that answers each call with the next of the given responses, built from the messages when it is a
    function, and with a plain answer once they run out."""

    def __init__(self, responses):
        super().__init__()
        self._responses = responses
        self.calls = 0

    def _next(self, messages) -> ModelResponse:
        self.calls += 1
        response = self._responses.pop(0) if self._responses else _answer()
        return response(messages) if callable(response) else response

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next(kwargs["messages"])

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next(kwargs["messages"])

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next(kwargs["messages"])

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next(kwargs["messages"])


def _tool_call(name: str, arguments: str) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[{"id": f"call-{name}", "type": "function", "function": {"name": name, "arguments": arguments}}],
        response_usage=MessageMetrics(input_tokens=6, output_tokens=4, total_tokens=10),
    )


def _answer() -> ModelResponse:
    return ModelResponse(
        role="assistant", content="ok", response_usage=MessageMetrics(input_tokens=6, output_tokens=4, total_tokens=10)
    )


async def _run_team(team, mode: str):
    if mode == "sync":
        return team.run("go")
    if mode == "stream":
        return list(team.run("go", stream=True, yield_run_output=True))[-1]
    if mode == "async":
        return await team.arun("go")
    return [event async for event in team.arun("go", stream=True, yield_run_output=True)][-1]


@pytest.mark.parametrize("mode", ["sync", "stream", "async", "async_stream"])
async def test_member_delegated_to_by_its_team_is_not_linked(mode: str):
    from agno.team import Team

    member = Agent(name="member", model=MockModel(), telemetry=False)
    leader = ScriptedModel([_tool_call("delegate_task_to_member", '{"member_id": "member", "task": "a"}')])
    team = Team(members=[member], model=leader, telemetry=False)

    team_run = await _run_team(team, mode)

    assert [member_run.called_from_run_id for member_run in team_run.member_responses] == [None]
    assert team_run.metrics.total_tokens == 10 * leader.calls


@pytest.mark.parametrize("mode", ["sync", "stream", "async", "async_stream"])
async def test_member_given_a_task_by_its_team_is_not_linked(mode: str):
    from agno.team import Team

    def execute_the_created_task(messages) -> ModelResponse:
        task_id = re.search(r"Task created: \[(\w+)\]", str(messages[-1].content)).group(1)
        return _tool_call("execute_task", json.dumps({"task_id": task_id, "member_id": "member"}))

    member = Agent(name="member", model=MockModel(), telemetry=False)
    leader = ScriptedModel(
        [_tool_call("create_task", '{"title": "a", "assignee": "member"}'), execute_the_created_task]
    )
    team = Team(members=[member], model=leader, mode="tasks", telemetry=False)

    team_run = await _run_team(team, mode)

    assert [member_run.called_from_run_id for member_run in team_run.member_responses] == [None]
    assert team_run.metrics.total_tokens == 10 * leader.calls
