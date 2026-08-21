"""Regression coverage for task-mode final-response transforms."""

import json
from typing import Any, AsyncIterator, Iterator

import pytest
from pydantic import BaseModel

from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.team import IntermediateRunContentEvent, RunCompletedEvent, RunContentEvent, TeamRunOutput
from agno.team import Team
from agno.team.mode import TeamMode
from agno.team.task import TaskList, save_task_list
from agno.tools import tool


class _ParsedAnswer(BaseModel):
    answer: str


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


class _RecordingScriptedModel(Model):
    """Offline model that records the exact context for every provider turn."""

    def __init__(self, script: list[tuple[Any, ...]], *, model_id: str = "tasks-script") -> None:
        super().__init__(id=model_id, name=model_id, provider="test")
        self.script = list(script)
        self.invoke_count = 0
        self.message_snapshots: list[list[str]] = []
        self._current_parsed: Any = None

    def _next(self, messages: list[Any]) -> ModelResponse:
        if self.invoke_count >= len(self.script):
            raise AssertionError("Script exhausted: an unexpected model call was made")

        self.message_snapshots.append([_message_text(message) for message in messages])
        turn = self.script[self.invoke_count]
        self.invoke_count += 1
        if turn[0] == "tool":
            _, name, arguments, tool_call_id = turn
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ]
        elif turn[0] == "parsed":
            response = ModelResponse(role="assistant", parsed=turn[1])
            self._current_parsed = turn[1]
            response.event = ModelResponseEvent.assistant_response.value
        else:
            response = ModelResponse(role="assistant", content=turn[1])
            response.event = ModelResponseEvent.assistant_response.value

        response.response_usage = MessageMetrics(input_tokens=1, output_tokens=1, total_tokens=2)
        return response

    def invoke(self, messages: list[Any], *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next(messages)

    async def ainvoke(self, messages: list[Any], *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next(messages)

    def invoke_stream(self, messages: list[Any], *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next(messages)

    async def ainvoke_stream(self, messages: list[Any], *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next(messages)

    def response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._current_parsed = None
        response = super().response(*args, **kwargs)
        response.parsed = self._current_parsed
        return response

    async def aresponse(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._current_parsed = None
        response = await super().aresponse(*args, **kwargs)
        response.parsed = self._current_parsed
        return response

    def parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def _tasks_team(model: Model, *, max_iterations: int = 2) -> Team:
    return Team(
        id="tasks-final-transform-team",
        name="Tasks Final Transform Team",
        members=[],
        mode=TeamMode.tasks,
        model=model,
        max_iterations=max_iterations,
        telemetry=False,
    )


def _seed_pending_task(team: Team) -> str:
    task_list = TaskList()
    task = task_list.create_task("Persisted work")
    team.session_state = {}
    save_task_list(team.session_state, task_list)
    return task.id


def _two_iteration_leader() -> tuple[_RecordingScriptedModel, Team]:
    leader = _RecordingScriptedModel([])
    team = _tasks_team(leader)
    task_id = _seed_pending_task(team)
    leader.script = [
        ("tool", "update_task_status", {"task_id": task_id, "status": "in_progress"}, "start-task"),
        ("content", "INTERMEDIATE PLANNING TEXT"),
        (
            "tool",
            "update_task_status",
            {"task_id": task_id, "status": "completed", "result": "Done."},
            "finish-task",
        ),
        ("content", "FINAL ANSWER"),
    ]
    return leader, team


def _two_iteration_leader_with_empty_final_turn() -> tuple[_RecordingScriptedModel, Team]:
    leader = _RecordingScriptedModel([])
    team = _tasks_team(leader)
    task_id = _seed_pending_task(team)
    leader.script = [
        ("tool", "update_task_status", {"task_id": task_id, "status": "in_progress"}, "start-task"),
        ("content", "INTERMEDIATE PLANNING TEXT"),
        (
            "tool",
            "update_task_status",
            {"task_id": task_id, "status": "completed", "result": "Done."},
            "finish-task",
        ),
        ("content", None),
    ]
    return leader, team


def _completed_content(events: list[Any]) -> Any:
    completed = [event for event in events if isinstance(event, RunCompletedEvent)]
    assert len(completed) == 1
    return completed[0].content


def test_sync_tasks_mode_returns_only_the_terminating_iteration_content():
    leader, team = _two_iteration_leader()

    response = team.run("finish the persisted work")

    assert response.content == "FINAL ANSWER"
    assert leader.invoke_count == 4


@pytest.mark.asyncio
async def test_async_tasks_mode_returns_only_the_terminating_iteration_content():
    leader, team = _two_iteration_leader()

    response = await team.arun("finish the persisted work")

    assert response.content == "FINAL ANSWER"
    assert leader.invoke_count == 4


def test_sync_tasks_mode_accepts_an_empty_parsed_object_without_retrying():
    leader = _RecordingScriptedModel([("parsed", {}), ("content", "UNEXPECTED RETRY")])
    team = _tasks_team(leader)
    team.output_schema = {"type": "object"}

    response = team.run("return an empty object")

    assert response.content == {}
    assert leader.invoke_count == 1


def test_sync_stream_tasks_mode_returns_only_the_terminating_iteration_content():
    leader, team = _two_iteration_leader()

    events = list(team.run("finish the persisted work", stream=True, stream_events=True))

    assert _completed_content(events) == "FINAL ANSWER"
    assert leader.invoke_count == 4


@pytest.mark.asyncio
async def test_async_stream_tasks_mode_returns_only_the_terminating_iteration_content():
    leader, team = _two_iteration_leader()

    events = [event async for event in team.arun("finish the persisted work", stream=True, stream_events=True)]

    assert _completed_content(events) == "FINAL ANSWER"
    assert leader.invoke_count == 4


def test_sync_default_stream_emits_only_the_terminating_iteration_content():
    leader, team = _two_iteration_leader()

    chunks = list(team.run("finish the persisted work", stream=True))

    assert [chunk.content for chunk in chunks if isinstance(chunk, RunContentEvent)] == ["FINAL ANSWER"]
    assert leader.invoke_count == 4


@pytest.mark.asyncio
async def test_async_default_stream_emits_only_the_terminating_iteration_content():
    leader, team = _two_iteration_leader()

    chunks = [chunk async for chunk in team.arun("finish the persisted work", stream=True)]

    assert [chunk.content for chunk in chunks if isinstance(chunk, RunContentEvent)] == ["FINAL ANSWER"]
    assert leader.invoke_count == 4


def test_stream_events_identify_and_store_nonterminal_content_as_intermediate():
    leader, team = _two_iteration_leader()
    team.store_events = True
    team.events_to_skip = []

    events = list(
        team.run(
            "finish the persisted work",
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    )

    run_outputs = [event for event in events if isinstance(event, TeamRunOutput)]
    assert len(run_outputs) == 1
    run_output = run_outputs[0]
    stored_events = run_output.events or []
    stored_intermediate = [event for event in stored_events if isinstance(event, IntermediateRunContentEvent)]
    stored_final = [event for event in stored_events if isinstance(event, RunContentEvent)]
    assert [event.content for event in stored_intermediate] == ["INTERMEDIATE PLANNING TEXT"]
    assert [event.content for event in stored_final] == ["FINAL ANSWER"]
    assert stored_intermediate[0].run_id == run_output.run_id
    assert stored_intermediate[0].session_id == run_output.session_id
    assert stored_intermediate[0].team_id == team.id


def test_sync_tasks_mode_does_not_retain_content_when_the_terminating_iteration_is_empty():
    leader, team = _two_iteration_leader_with_empty_final_turn()

    response = team.run("finish the persisted work")

    assert response.content is None
    assert leader.invoke_count == 4


@pytest.mark.asyncio
async def test_async_tasks_mode_does_not_retain_content_when_the_terminating_iteration_is_empty():
    leader, team = _two_iteration_leader_with_empty_final_turn()

    response = await team.arun("finish the persisted work")

    assert response.content is None
    assert leader.invoke_count == 4


def test_sync_stream_tasks_mode_does_not_retain_content_when_the_terminating_iteration_is_empty():
    leader, team = _two_iteration_leader_with_empty_final_turn()

    events = list(team.run("finish the persisted work", stream=True, stream_events=True))

    assert _completed_content(events) is None
    assert leader.invoke_count == 4


@pytest.mark.asyncio
async def test_async_stream_tasks_mode_does_not_retain_content_when_the_terminating_iteration_is_empty():
    leader, team = _two_iteration_leader_with_empty_final_turn()

    events = [event async for event in team.arun("finish the persisted work", stream=True, stream_events=True)]

    assert _completed_content(events) is None
    assert leader.invoke_count == 4


def _fixed_transform_model(model_id: str, content: Any) -> _RecordingScriptedModel:
    script = [("parsed", content)] if isinstance(content, BaseModel) else [("content", content)]
    return _RecordingScriptedModel(script, model_id=model_id)


def _configure_empty_transform(team: Team, transform: str) -> _RecordingScriptedModel:
    empty_transform = _fixed_transform_model(f"empty-{transform}", None)
    if transform == "output":
        team.output_model = empty_transform
    else:
        team.output_schema = _ParsedAnswer
        team.parser_model = empty_transform
    return empty_transform


@pytest.mark.parametrize("transform", ["output", "parser"])
def test_sync_empty_final_transform_is_authoritative(transform: str):
    leader, team = _two_iteration_leader()
    transformer = _configure_empty_transform(team, transform)

    response = team.run("finish the persisted work")

    assert response.content is None
    assert transformer.invoke_count == 1


@pytest.mark.parametrize("transform", ["output", "parser"])
@pytest.mark.asyncio
async def test_async_empty_final_transform_is_authoritative(transform: str):
    leader, team = _two_iteration_leader()
    transformer = _configure_empty_transform(team, transform)

    response = await team.arun("finish the persisted work")

    assert response.content is None
    assert transformer.invoke_count == 1


@pytest.mark.parametrize("transform", ["output", "parser"])
def test_sync_stream_empty_final_transform_is_authoritative(transform: str):
    leader, team = _two_iteration_leader()
    transformer = _configure_empty_transform(team, transform)

    events = list(team.run("finish the persisted work", stream=True, stream_events=True))

    assert _completed_content(events) is None
    assert transformer.invoke_count == 1


@pytest.mark.parametrize("transform", ["output", "parser"])
@pytest.mark.asyncio
async def test_async_stream_empty_final_transform_is_authoritative(transform: str):
    leader, team = _two_iteration_leader()
    transformer = _configure_empty_transform(team, transform)

    events = [event async for event in team.arun("finish the persisted work", stream=True, stream_events=True)]

    assert _completed_content(events) is None
    assert transformer.invoke_count == 1


def test_sync_output_model_runs_only_for_the_terminating_iteration():
    leader, team = _two_iteration_leader()
    formatter = _fixed_transform_model("formatter", "FORMATTED FINAL ANSWER")
    team.output_model = formatter

    response = team.run("finish the persisted work")

    assert response.content == "FORMATTED FINAL ANSWER"
    assert formatter.invoke_count == 1


@pytest.mark.asyncio
async def test_async_output_model_runs_only_for_the_terminating_iteration():
    leader, team = _two_iteration_leader()
    formatter = _fixed_transform_model("formatter", "FORMATTED FINAL ANSWER")
    team.output_model = formatter

    response = await team.arun("finish the persisted work")

    assert response.content == "FORMATTED FINAL ANSWER"
    assert formatter.invoke_count == 1


def test_sync_stream_output_model_runs_only_for_the_terminating_iteration():
    leader, team = _two_iteration_leader()
    formatter = _fixed_transform_model("formatter", "FORMATTED FINAL ANSWER")
    team.output_model = formatter

    events = list(team.run("finish the persisted work", stream=True, stream_events=True))

    assert _completed_content(events) == "FORMATTED FINAL ANSWER"
    assert formatter.invoke_count == 1


@pytest.mark.asyncio
async def test_async_stream_output_model_runs_only_for_the_terminating_iteration():
    leader, team = _two_iteration_leader()
    formatter = _fixed_transform_model("formatter", "FORMATTED FINAL ANSWER")
    team.output_model = formatter

    events = [event async for event in team.arun("finish the persisted work", stream=True, stream_events=True)]

    assert _completed_content(events) == "FORMATTED FINAL ANSWER"
    assert formatter.invoke_count == 1


def _configure_parser(team: Team) -> _RecordingScriptedModel:
    parser = _fixed_transform_model("parser", '{"answer":"PARSED FINAL SENTINEL"}')
    team.output_schema = _ParsedAnswer
    team.parser_model = parser
    return parser


def test_sync_parser_model_runs_only_for_final_iteration_without_polluting_leader_context():
    leader, team = _two_iteration_leader()
    parser = _configure_parser(team)

    response = team.run("finish the persisted work")

    assert response.content == _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    assert parser.invoke_count == 1
    assert "PARSED FINAL SENTINEL" not in "\n".join(leader.message_snapshots[2])


@pytest.mark.asyncio
async def test_async_parser_model_runs_only_for_final_iteration_without_polluting_leader_context():
    leader, team = _two_iteration_leader()
    parser = _configure_parser(team)

    response = await team.arun("finish the persisted work")

    assert response.content == _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    assert parser.invoke_count == 1
    assert "PARSED FINAL SENTINEL" not in "\n".join(leader.message_snapshots[2])


def test_sync_stream_parser_model_runs_only_for_the_terminating_iteration():
    leader, team = _two_iteration_leader()
    parser = _configure_parser(team)

    events = list(team.run("finish the persisted work", stream=True, stream_events=True))

    assert _completed_content(events) == _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    assert parser.invoke_count == 1


@pytest.mark.asyncio
async def test_async_stream_parser_model_runs_only_for_the_terminating_iteration():
    leader, team = _two_iteration_leader()
    parser = _configure_parser(team)

    events = [event async for event in team.arun("finish the persisted work", stream=True, stream_events=True)]

    assert _completed_content(events) == _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    assert parser.invoke_count == 1


def test_sync_stream_with_output_and_parser_models_emits_only_the_parser_result():
    leader, team = _two_iteration_leader()
    formatter = _fixed_transform_model("formatter", "FORMATTED FINAL ANSWER")
    parser = _configure_parser(team)
    team.output_model = formatter

    chunks = list(team.run("finish the persisted work", stream=True))

    assert [chunk.content for chunk in chunks if isinstance(chunk, RunContentEvent)] == [
        _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    ]
    assert formatter.invoke_count == 1
    assert parser.invoke_count == 1


@pytest.mark.asyncio
async def test_async_stream_with_output_and_parser_models_emits_only_the_parser_result():
    leader, team = _two_iteration_leader()
    formatter = _fixed_transform_model("formatter", "FORMATTED FINAL ANSWER")
    parser = _configure_parser(team)
    team.output_model = formatter

    chunks = [chunk async for chunk in team.arun("finish the persisted work", stream=True)]

    assert [chunk.content for chunk in chunks if isinstance(chunk, RunContentEvent)] == [
        _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    ]
    assert formatter.invoke_count == 1
    assert parser.invoke_count == 1


@pytest.mark.parametrize("with_output_model", [False, True])
def test_sync_stream_does_not_suppress_final_content_for_an_inactive_parser(with_output_model: bool):
    leader, team = _two_iteration_leader()
    parser = _fixed_transform_model("inactive-parser", "MUST NOT RUN")
    team.parser_model = parser
    formatter = _fixed_transform_model("formatter", "FORMATTED FINAL ANSWER")
    if with_output_model:
        team.output_model = formatter

    chunks = list(team.run("finish the persisted work", stream=True))

    expected = "FORMATTED FINAL ANSWER" if with_output_model else "FINAL ANSWER"
    assert [chunk.content for chunk in chunks if isinstance(chunk, RunContentEvent)] == [expected]
    assert parser.invoke_count == 0
    assert formatter.invoke_count == int(with_output_model)


@pytest.mark.parametrize("with_output_model", [False, True])
@pytest.mark.asyncio
async def test_async_stream_does_not_suppress_final_content_for_an_inactive_parser(with_output_model: bool):
    leader, team = _two_iteration_leader()
    parser = _fixed_transform_model("inactive-parser", "MUST NOT RUN")
    team.parser_model = parser
    formatter = _fixed_transform_model("formatter", "FORMATTED FINAL ANSWER")
    if with_output_model:
        team.output_model = formatter

    chunks = [chunk async for chunk in team.arun("finish the persisted work", stream=True)]

    expected = "FORMATTED FINAL ANSWER" if with_output_model else "FINAL ANSWER"
    assert [chunk.content for chunk in chunks if isinstance(chunk, RunContentEvent)] == [expected]
    assert parser.invoke_count == 0
    assert formatter.invoke_count == int(with_output_model)


def _max_iteration_team() -> tuple[_RecordingScriptedModel, Team]:
    leader = _RecordingScriptedModel([("content", "FIRST DRAFT"), ("content", "LAST DRAFT")])
    team = _tasks_team(leader, max_iterations=2)
    _seed_pending_task(team)
    return leader, team


def test_sync_default_stream_emits_only_the_last_max_iteration_content():
    leader, team = _max_iteration_team()

    chunks = list(team.run("make progress", stream=True))

    assert [chunk.content for chunk in chunks if isinstance(chunk, RunContentEvent)] == ["LAST DRAFT"]
    assert leader.invoke_count == 2


@pytest.mark.asyncio
async def test_async_default_stream_emits_only_the_last_max_iteration_content():
    leader, team = _max_iteration_team()

    chunks = [chunk async for chunk in team.arun("make progress", stream=True)]

    assert [chunk.content for chunk in chunks if isinstance(chunk, RunContentEvent)] == ["LAST DRAFT"]
    assert leader.invoke_count == 2


def test_sync_output_model_runs_once_on_the_max_iteration_final_turn():
    leader, team = _max_iteration_team()
    formatter = _fixed_transform_model("formatter", "FORMATTED LAST DRAFT")
    team.output_model = formatter

    response = team.run("make progress")

    assert response.content == "FORMATTED LAST DRAFT"
    assert leader.invoke_count == 2
    assert formatter.invoke_count == 1


@pytest.mark.asyncio
async def test_async_output_model_runs_once_on_the_max_iteration_final_turn():
    leader, team = _max_iteration_team()
    formatter = _fixed_transform_model("formatter", "FORMATTED LAST DRAFT")
    team.output_model = formatter

    response = await team.arun("make progress")

    assert response.content == "FORMATTED LAST DRAFT"
    assert leader.invoke_count == 2
    assert formatter.invoke_count == 1


def test_sync_stream_output_model_runs_once_on_the_max_iteration_final_turn():
    leader, team = _max_iteration_team()
    formatter = _fixed_transform_model("formatter", "FORMATTED LAST DRAFT")
    team.output_model = formatter

    events = list(team.run("make progress", stream=True, stream_events=True))

    assert _completed_content(events) == "FORMATTED LAST DRAFT"
    assert leader.invoke_count == 2
    assert formatter.invoke_count == 1


@pytest.mark.asyncio
async def test_async_stream_output_model_runs_once_on_the_max_iteration_final_turn():
    leader, team = _max_iteration_team()
    formatter = _fixed_transform_model("formatter", "FORMATTED LAST DRAFT")
    team.output_model = formatter

    events = [event async for event in team.arun("make progress", stream=True, stream_events=True)]

    assert _completed_content(events) == "FORMATTED LAST DRAFT"
    assert leader.invoke_count == 2
    assert formatter.invoke_count == 1


def test_sync_parser_model_runs_once_on_the_max_iteration_final_turn():
    leader, team = _max_iteration_team()
    parser = _configure_parser(team)

    response = team.run("make progress")

    assert response.content == _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    assert leader.invoke_count == 2
    assert parser.invoke_count == 1
    assert "PARSED FINAL SENTINEL" not in "\n".join(leader.message_snapshots[1])


@pytest.mark.asyncio
async def test_async_parser_model_runs_once_on_the_max_iteration_final_turn():
    leader, team = _max_iteration_team()
    parser = _configure_parser(team)

    response = await team.arun("make progress")

    assert response.content == _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    assert leader.invoke_count == 2
    assert parser.invoke_count == 1
    assert "PARSED FINAL SENTINEL" not in "\n".join(leader.message_snapshots[1])


def test_sync_stream_parser_model_runs_once_on_the_max_iteration_final_turn():
    leader, team = _max_iteration_team()
    parser = _configure_parser(team)

    events = list(team.run("make progress", stream=True, stream_events=True))

    assert _completed_content(events) == _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    assert leader.invoke_count == 2
    assert parser.invoke_count == 1


@pytest.mark.asyncio
async def test_async_stream_parser_model_runs_once_on_the_max_iteration_final_turn():
    leader, team = _max_iteration_team()
    parser = _configure_parser(team)

    events = [event async for event in team.arun("make progress", stream=True, stream_events=True)]

    assert _completed_content(events) == _ParsedAnswer(answer="PARSED FINAL SENTINEL")
    assert leader.invoke_count == 2
    assert parser.invoke_count == 1


_HITL_EXECUTIONS: list[str] = []


@tool(name="confirm_action", requires_confirmation=True)
def _confirm_action(item: str) -> str:
    _HITL_EXECUTIONS.append(item)
    return f"confirmed {item}"


def _paused_transform_team() -> tuple[Team, _RecordingScriptedModel, _RecordingScriptedModel]:
    leader = _RecordingScriptedModel([("tool", "confirm_action", {"item": "release"}, "confirm-1")])
    formatter = _fixed_transform_model("formatter", "MUST NOT RUN")
    parser = _fixed_transform_model("parser", '{"answer":"MUST NOT RUN"}')
    team = _tasks_team(leader, max_iterations=1)
    team.tools = [_confirm_action]
    team.output_model = formatter
    team.output_schema = _ParsedAnswer
    team.parser_model = parser
    return team, formatter, parser


def test_sync_stream_does_not_transform_before_an_unresolved_hitl_pause():
    _HITL_EXECUTIONS.clear()
    team, formatter, parser = _paused_transform_team()

    list(team.run("request confirmation", stream=True, stream_events=True))

    assert formatter.invoke_count == 0
    assert parser.invoke_count == 0
    assert _HITL_EXECUTIONS == []


@pytest.mark.asyncio
async def test_async_stream_does_not_transform_before_an_unresolved_hitl_pause():
    _HITL_EXECUTIONS.clear()
    team, formatter, parser = _paused_transform_team()

    _ = [event async for event in team.arun("request confirmation", stream=True, stream_events=True)]

    assert formatter.invoke_count == 0
    assert parser.invoke_count == 0
    assert _HITL_EXECUTIONS == []
