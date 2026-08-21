"""Deterministic coverage for tasks-mode direct-response loop behavior."""

import json
from typing import Any, AsyncIterator, Iterator

import pytest

from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.team import (
    RunCompletedEvent,
    RunContentEvent,
    RunStartedEvent,
    TaskIterationCompletedEvent,
    TaskIterationStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.team import Team
from agno.team.mode import TeamMode
from agno.team.task import TaskList, TaskStatus, load_task_list, save_task_list


class _ScriptedModel(Model):
    """Offline model whose provider turns are content or task-tool calls."""

    def __init__(self, script: list[tuple[Any, ...]]) -> None:
        super().__init__(id="tasks-script", name="tasks-script", provider="test")
        self.script = list(script)
        self.invoke_count = 0
        self.outer_responses: list[ModelResponse] = []

    def _next(self) -> ModelResponse:
        if self.invoke_count >= len(self.script):
            raise AssertionError("Script exhausted: the tasks loop made an unexpected model call")

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
        else:
            response = ModelResponse(role="assistant", content=turn[1])
            response.event = ModelResponseEvent.assistant_response.value

        response.response_usage = MessageMetrics(input_tokens=1, output_tokens=1, total_tokens=2)
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        response = super().response(*args, **kwargs)
        self.outer_responses.append(response)
        return response

    async def aresponse(self, *args: Any, **kwargs: Any) -> ModelResponse:
        response = await super().aresponse(*args, **kwargs)
        self.outer_responses.append(response)
        return response

    def parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def _tasks_team(model: Model, *, max_iterations: int = 3) -> Team:
    return Team(
        id="tasks-team",
        name="Tasks Team",
        members=[],
        mode=TeamMode.tasks,
        model=model,
        max_iterations=max_iterations,
        telemetry=False,
    )


class TestTasksModePrompt:
    """Keep the user-facing direct-response contract pinned in the prompt."""

    def test_tasks_mode_prompt_contains_direct_response_and_completion_guidance(self):
        from agno.team._messages import _get_mode_instructions

        instructions = _get_mode_instructions(_tasks_team(_ScriptedModel([("content", "unused")])))

        assert "respond without creating tasks or delegating" in instructions
        assert "Only call `mark_all_complete` when you actually created and executed tasks" in instructions
        assert "Do not over-decompose" in instructions
        assert "genuinely independent" in instructions

    @pytest.mark.parametrize("mode", [TeamMode.coordinate, TeamMode.route, TeamMode.broadcast])
    def test_other_modes_keep_their_direct_response_clause(self, mode: TeamMode):
        from agno.team._messages import _get_mode_instructions

        team = Team(name="test", members=[], mode=mode)

        assert "respond without delegating" in _get_mode_instructions(team)


def test_sync_tasks_loop_returns_direct_content_after_one_outer_iteration():
    model = _ScriptedModel([("content", "Hello directly.")])

    response = _tasks_team(model).run("hello")

    assert response.content == "Hello directly."
    assert model.invoke_count == 1
    assert len(model.outer_responses) == 1
    assert not model.outer_responses[0].tool_calls


@pytest.mark.asyncio
async def test_async_tasks_loop_returns_direct_content_after_one_outer_iteration():
    model = _ScriptedModel([("content", "Hello directly.")])

    response = await _tasks_team(model).arun("hello")

    assert response.content == "Hello directly."
    assert model.invoke_count == 1
    assert len(model.outer_responses) == 1
    assert not model.outer_responses[0].tool_calls


def test_sync_tasks_loop_retries_after_empty_first_turn():
    model = _ScriptedModel([("content", None), ("content", "Recovered response.")])

    response = _tasks_team(model).run("answer me")

    assert response.content == "Recovered response."
    assert model.invoke_count == 2
    assert len(model.outer_responses) == 2


@pytest.mark.asyncio
async def test_async_tasks_loop_retries_after_empty_first_turn():
    model = _ScriptedModel([("content", ""), ("content", "Recovered response.")])

    response = await _tasks_team(model).arun("answer me")

    assert response.content == "Recovered response."
    assert model.invoke_count == 2
    assert len(model.outer_responses) == 2


def test_sync_task_activity_forces_an_outer_iteration_when_aggregate_tool_calls_are_empty():
    model = _ScriptedModel(
        [
            ("tool", "create_task", {"title": "Investigate"}, "create-1"),
            ("content", "I created the plan."),
            ("tool", "mark_all_complete", {"summary": "Plan handled."}, "complete-1"),
            ("content", "Plan handled."),
        ]
    )

    response = _tasks_team(model, max_iterations=2).run("investigate this")

    assert model.invoke_count == 4
    assert len(model.outer_responses) == 2
    assert not model.outer_responses[0].tool_calls
    assert {tool.tool_name for tool in response.tools or []} == {"create_task", "mark_all_complete"}


@pytest.mark.asyncio
async def test_async_task_activity_forces_an_outer_iteration_when_aggregate_tool_calls_are_empty():
    model = _ScriptedModel(
        [
            ("tool", "create_task", {"title": "Investigate"}, "create-1"),
            ("content", "I created the plan."),
            ("tool", "mark_all_complete", {"summary": "Plan handled."}, "complete-1"),
            ("content", "Plan handled."),
        ]
    )

    response = await _tasks_team(model, max_iterations=2).arun("investigate this")

    assert model.invoke_count == 4
    assert len(model.outer_responses) == 2
    assert not model.outer_responses[0].tool_calls
    assert {tool.tool_name for tool in response.tools or []} == {"create_task", "mark_all_complete"}


def test_sync_plain_content_does_not_abandon_unfinished_persisted_task():
    session_state: dict[str, Any] = {}
    task_list = TaskList()
    pending = task_list.create_task("Persisted work")
    save_task_list(session_state, task_list)
    model = _ScriptedModel(
        [
            ("content", "I will continue the existing work."),
            (
                "tool",
                "update_task_status",
                {"task_id": pending.id, "status": "completed", "result": "Finished."},
                "complete-persisted",
            ),
            ("content", "Finished persisted work."),
        ]
    )
    team = _tasks_team(model, max_iterations=2)
    team.session_state = session_state

    response = team.run("continue")

    assert model.invoke_count == 3, "plain content incorrectly exited while persisted work was pending"
    assert len(model.outer_responses) == 2
    assert {tool.tool_name for tool in response.tools or []} == {"update_task_status"}
    assert len(response.tools or []) == 1
    assert f"Task [{pending.id}] 'Persisted work' updated to completed." in (response.tools or [])[0].result
    persisted = load_task_list(response.session_state).get_task(pending.id)
    assert persisted is not None
    assert (persisted.status, persisted.result) == (TaskStatus.completed, "Finished.")


@pytest.mark.asyncio
async def test_async_plain_content_does_not_abandon_unfinished_persisted_task():
    session_state: dict[str, Any] = {}
    task_list = TaskList()
    pending = task_list.create_task("Persisted work")
    save_task_list(session_state, task_list)
    model = _ScriptedModel(
        [
            ("content", "I will continue the existing work."),
            (
                "tool",
                "cancel_task",
                {"task_id": pending.id, "reason": "No longer needed"},
                "cancel-persisted",
            ),
            ("content", "Replanned persisted work."),
        ]
    )
    team = _tasks_team(model, max_iterations=2)
    team.session_state = session_state

    response = await team.arun("continue")

    assert model.invoke_count == 3, "plain content incorrectly exited while persisted work was pending"
    assert len(model.outer_responses) == 2
    assert {tool.tool_name for tool in response.tools or []} == {"cancel_task"}
    assert len(response.tools or []) == 1
    assert f"Task [{pending.id}] 'Persisted work' cancelled." in (response.tools or [])[0].result


def _assert_one_paired_stream_iteration(events: list[Any]) -> None:
    run_started = [event for event in events if isinstance(event, RunStartedEvent)]
    run_completed = [event for event in events if isinstance(event, RunCompletedEvent)]
    iteration_started = [event for event in events if isinstance(event, TaskIterationStartedEvent)]
    iteration_completed = [event for event in events if isinstance(event, TaskIterationCompletedEvent)]

    assert len(run_started) == len(run_completed) == 1
    assert [event.iteration for event in iteration_started] == [1]
    assert [event.iteration for event in iteration_completed] == [1]
    assert (
        iteration_started[0].run_id == iteration_completed[0].run_id == run_started[0].run_id == run_completed[0].run_id
    )


def test_sync_stream_direct_response_pairs_events_and_runs_one_iteration():
    model = _ScriptedModel([("content", "Streamed directly.")])

    events = list(_tasks_team(model).run("hello", stream=True, stream_events=True))

    _assert_one_paired_stream_iteration(events)
    assert model.invoke_count == 1


@pytest.mark.asyncio
async def test_async_stream_direct_response_pairs_events_and_runs_one_iteration():
    model = _ScriptedModel([("content", "Streamed directly.")])

    events = [event async for event in _tasks_team(model).arun("hello", stream=True, stream_events=True)]

    _assert_one_paired_stream_iteration(events)
    assert model.invoke_count == 1


def _assert_leader_tool_direct_stream(events: list[Any], calls: list[str]) -> None:
    _assert_one_paired_stream_iteration(events)
    content_events = [event for event in events if isinstance(event, RunContentEvent)]
    tool_started = [
        event
        for event in events
        if isinstance(event, ToolCallStartedEvent) and event.tool and event.tool.tool_name == "leader_lookup"
    ]
    tool_completed = [
        event
        for event in events
        if isinstance(event, ToolCallCompletedEvent) and event.tool and event.tool.tool_name == "leader_lookup"
    ]

    assert calls == ["weather"]
    assert [event.content for event in content_events] == ["Leader answer."]
    assert len(tool_started) == len(tool_completed) == 1
    assert tool_started[0].tool.tool_call_id == tool_completed[0].tool.tool_call_id  # type: ignore[union-attr]


def test_sync_stream_leader_tool_then_direct_response_exits_once_without_duplicates():
    calls: list[str] = []

    def leader_lookup(topic: str) -> str:
        calls.append(topic)
        return "sunny"

    model = _ScriptedModel(
        [
            ("tool", "leader_lookup", {"topic": "weather"}, "leader-1"),
            ("content", "Leader answer."),
        ]
    )
    team = _tasks_team(model)
    team.tools = [leader_lookup]

    events = list(team.run("check weather", stream=True, stream_events=True))

    _assert_leader_tool_direct_stream(events, calls)
    assert model.invoke_count == 2


@pytest.mark.asyncio
async def test_async_stream_leader_tool_then_direct_response_exits_once_without_duplicates():
    calls: list[str] = []

    def leader_lookup(topic: str) -> str:
        calls.append(topic)
        return "sunny"

    model = _ScriptedModel(
        [
            ("tool", "leader_lookup", {"topic": "weather"}, "leader-1"),
            ("content", "Leader answer."),
        ]
    )
    team = _tasks_team(model)
    team.tools = [leader_lookup]

    events = [event async for event in team.arun("check weather", stream=True, stream_events=True)]

    _assert_leader_tool_direct_stream(events, calls)
    assert model.invoke_count == 2
