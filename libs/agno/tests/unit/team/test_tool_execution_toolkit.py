"""Unit tests for the toolkit a team run records on each tool execution."""

from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.run.team import TeamRunEvent
from agno.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.toolkit import Toolkit


class ScriptedModel(Model):
    """Minimal offline model: answers each call with the next of the given responses."""

    def __init__(self, responses: List[ModelResponse]):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._responses = responses

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
        return self._responses.pop(0)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._responses.pop(0)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._responses.pop(0)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._responses.pop(0)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def count_files() -> str:
    """Count the files."""
    return "3 files"


def _responses() -> List[ModelResponse]:
    return [
        ModelResponse(
            role="assistant",
            tool_calls=[
                {"id": "call-add", "type": "function", "function": {"name": "add", "arguments": '{"a": 1, "b": 2}'}},
                {"id": "call-count", "type": "function", "function": {"name": "count_files", "arguments": "{}"}},
            ],
        ),
        ModelResponse(role="assistant", content="done"),
    ]


def _confirmation_team(db_file: str) -> Team:
    return Team(
        model=ScriptedModel(
            [
                ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {"id": "call-count", "type": "function", "function": {"name": "count_files", "arguments": "{}"}}
                    ],
                ),
                ModelResponse(role="assistant", content="done"),
            ]
        ),
        members=[Agent(name="member", model=ScriptedModel([]), telemetry=False)],
        tools=[Toolkit(name="files", tools=[count_files], requires_confirmation_tools=["count_files"])],
        db=SqliteDb(db_file=db_file),
        telemetry=False,
    )


def test_team_run_stores_the_toolkit_of_each_tool_execution(tmp_path):
    """A team tool from a Toolkit records the toolkit's name on its stored tool execution; a plain function none."""
    calculator = CalculatorTools()
    team = Team(
        model=ScriptedModel(_responses()),
        members=[Agent(name="member", model=ScriptedModel([]), telemetry=False)],
        tools=[calculator, count_files],
        db=SqliteDb(db_file=str(tmp_path / "team.db")),
        telemetry=False,
    )

    run_output = team.run("add 1 and 2, then count the files", session_id="s")

    stored = team.get_last_run_output(session_id="s")
    for tools in (run_output.tools, stored.tools):
        assert {tool.tool_name: tool.toolkit for tool in tools} == {"add": "calculator", "count_files": None}
    # The Toolkit's own functions are left as they were.
    assert calculator.functions["add"].owning_toolkit is None


@pytest.mark.asyncio
async def test_team_arun_stores_the_toolkit_of_each_tool_execution(tmp_path):
    """The async team run path records the toolkit's name the same way the sync path does."""
    team = Team(
        model=ScriptedModel(_responses()),
        members=[Agent(name="member", model=ScriptedModel([]), telemetry=False)],
        tools=[CalculatorTools(), count_files],
        db=SqliteDb(db_file=str(tmp_path / "team.db")),
        telemetry=False,
    )

    run_output = await team.arun("add 1 and 2, then count the files", session_id="s")

    stored = team.get_last_run_output(session_id="s")
    for tools in (run_output.tools, stored.tools):
        assert {tool.tool_name: tool.toolkit for tool in tools} == {"add": "calculator", "count_files": None}


def test_team_streamed_run_stores_the_toolkit_of_each_tool_execution(tmp_path):
    """The streamed team run path records the toolkit's name on the stored tool executions and completed events."""
    team = Team(
        model=ScriptedModel(_responses()),
        members=[Agent(name="member", model=ScriptedModel([]), telemetry=False)],
        tools=[CalculatorTools(), count_files],
        db=SqliteDb(db_file=str(tmp_path / "team.db")),
        telemetry=False,
    )

    events = list(team.run("add 1 and 2, then count the files", session_id="s", stream=True, stream_events=True))

    completed = {
        event.tool.tool_name: event.tool.toolkit
        for event in events
        if event.event == TeamRunEvent.tool_call_completed.value
    }
    assert completed == {"add": "calculator", "count_files": None}
    stored = team.get_last_run_output(session_id="s")
    assert {tool.tool_name: tool.toolkit for tool in stored.tools} == {"add": "calculator", "count_files": None}


def test_team_confirmed_tool_keeps_its_toolkit_and_duration(tmp_path):
    """A confirmed team Toolkit tool keeps the toolkit's name and stores its duration once the run continues."""
    team = _confirmation_team(str(tmp_path / "team.db"))

    paused = team.run("count the files", session_id="s")
    assert paused.status == RunStatus.paused
    assert paused.tools[0].toolkit == "files"

    for requirement in paused.active_requirements:
        requirement.confirm()
    resumed = team.continue_run(run_id=paused.run_id, session_id="s", requirements=paused.requirements)

    assert resumed.status == RunStatus.completed
    stored = team.get_last_run_output(session_id="s")
    for tools in (resumed.tools, stored.tools):
        assert tools[0].toolkit == "files"
        assert tools[0].result == "3 files"
        assert tools[0].metrics is not None and tools[0].metrics.duration > 0


@pytest.mark.asyncio
async def test_team_confirmed_tool_keeps_its_toolkit_and_duration_async(tmp_path):
    """A confirmed team Toolkit tool keeps the toolkit's name and stores its execution duration on the async path."""
    team = _confirmation_team(str(tmp_path / "team.db"))

    paused = await team.arun("count the files", session_id="s")
    assert paused.status == RunStatus.paused
    assert paused.tools[0].toolkit == "files"

    for requirement in paused.active_requirements:
        requirement.confirm()
    resumed = await team.acontinue_run(run_id=paused.run_id, session_id="s", requirements=paused.requirements)

    assert resumed.status == RunStatus.completed
    stored = team.get_last_run_output(session_id="s")
    for tools in (resumed.tools, stored.tools):
        assert tools[0].toolkit == "files"
        assert tools[0].result == "3 files"
        assert tools[0].metrics is not None and tools[0].metrics.duration > 0
