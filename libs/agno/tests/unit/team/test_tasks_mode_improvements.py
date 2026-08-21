"""Deterministic unit coverage for task tools and task-state persistence."""

import json
from typing import Any, AsyncIterator, Iterator
from unittest.mock import MagicMock

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TaskIterationCompletedEvent, TaskIterationStartedEvent, TaskUpdatedEvent, TeamRunOutput
from agno.session import TeamSession
from agno.team import Team
from agno.team._task_tools import _get_task_management_tools
from agno.team.mode import TeamMode
from agno.team.task import TaskList, TaskStatus, load_task_list, save_task_list
from agno.tools.function import Function


class _MultiRunTaskModel(Model):
    """Drive two task goals over three deterministic outer model calls."""

    def __init__(self) -> None:
        super().__init__(id="multi-run-task-model", name="multi-run-task-model", provider="test")
        self.response_count = 0
        self.second_task_id: str | None = None
        self.second_run_task_summary: str | None = None
        self.tool_actions: list[tuple[str, str]] = []

    @staticmethod
    def _tool_map(tools: list[Function]) -> dict[str, Function]:
        return {tool.name: tool for tool in tools}

    @staticmethod
    def _create_task(tools: dict[str, Function], title: str) -> str:
        create_task = tools["create_task"].entrypoint
        assert create_task is not None
        output = list(create_task(title=title))
        task_id = output[-1].split("[", 1)[1].split("]", 1)[0]
        assert task_id
        return task_id

    @staticmethod
    def _complete_task(tools: dict[str, Function], task_id: str, result: str) -> None:
        update_task_status = tools["update_task_status"].entrypoint
        assert update_task_status is not None
        list(update_task_status(task_id=task_id, status=TaskStatus.completed.value, result=result))

    @staticmethod
    def _complete_goal(tools: dict[str, Function], summary: str) -> None:
        mark_all_complete = tools["mark_all_complete"].entrypoint
        assert mark_all_complete is not None
        mark_all_complete(summary=summary)

    def response(self, *, tools: list[Function], **kwargs: Any) -> ModelResponse:
        self.response_count += 1
        task_tools = self._tool_map(tools)

        if self.response_count == 1:
            first_task_id = self._create_task(task_tools, "First task")
            self.tool_actions.append(("create_task", "First task"))
            self._complete_task(task_tools, first_task_id, "First result")
            self.tool_actions.append(("update_task_status", "First result"))
            self._complete_goal(task_tools, "First goal complete")
            self.tool_actions.append(("mark_all_complete", "First goal complete"))
            return ModelResponse(role="assistant", content="First goal complete.")

        if self.response_count == 2:
            list_tasks = task_tools["list_tasks"].entrypoint
            assert list_tasks is not None
            self.second_run_task_summary = list_tasks()
            self.tool_actions.append(("list_tasks", ""))
            self.second_task_id = self._create_task(task_tools, "Second task")
            self.tool_actions.append(("create_task", "Second task"))
            return ModelResponse(role="assistant", content="Second task created.")

        if self.response_count == 3:
            assert self.second_task_id is not None
            self._complete_task(task_tools, self.second_task_id, "Second result")
            self.tool_actions.append(("update_task_status", "Second result"))
            self._complete_goal(task_tools, "Second goal complete")
            self.tool_actions.append(("mark_all_complete", "Second goal complete"))
            return ModelResponse(role="assistant", content="Second goal complete.")

        raise AssertionError("Task loop made an unexpected model call")

    async def aresponse(self, *, tools: list[Function], **kwargs: Any) -> ModelResponse:
        return self.response(tools=tools, **kwargs)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        return iter(())

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        for response in ():
            yield response

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


class _CancellationReplanModel(Model):
    """Cancel obsolete work, then create and complete its replacement."""

    def __init__(self, obsolete_task_id: str) -> None:
        super().__init__(id="cancellation-replan-model", name="cancellation-replan-model", provider="test")
        self.obsolete_task_id = obsolete_task_id
        self.invoke_count = 0
        self.replacement_task_id: str | None = None

    @staticmethod
    def _tool_response(name: str, arguments: dict[str, Any], tool_call_id: str) -> ModelResponse:
        response = ModelResponse(role="assistant")
        response.tool_calls = [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ]
        return response

    @staticmethod
    def _content_response(content: str) -> ModelResponse:
        response = ModelResponse(role="assistant", content=content)
        response.event = ModelResponseEvent.assistant_response.value
        return response

    @staticmethod
    def _created_task_id(messages: list[Any]) -> str:
        for message in reversed(messages):
            if getattr(message, "role", None) != "tool" or getattr(message, "tool_name", None) != "create_task":
                continue
            content = getattr(message, "content", "")
            content_text = "".join(str(item) for item in content) if isinstance(content, list) else str(content)
            if "[" in content_text and "]" in content_text:
                return content_text.split("[", 1)[1].split("]", 1)[0]
        raise AssertionError("create_task result was not available to the next model turn")

    def _next(self, messages: list[Any]) -> ModelResponse:
        step = self.invoke_count
        self.invoke_count += 1

        if step == 0:
            return self._tool_response(
                "cancel_task",
                {"task_id": self.obsolete_task_id, "reason": "Superseded by a better plan"},
                "cancel-obsolete",
            )
        if step == 1:
            return self._content_response("Obsolete work cancelled.")
        if step == 2:
            return self._tool_response("create_task", {"title": "Replacement work"}, "create-replacement")
        if step == 3:
            self.replacement_task_id = self._created_task_id(messages)
            return self._tool_response(
                "update_task_status",
                {
                    "task_id": self.replacement_task_id,
                    "status": TaskStatus.completed.value,
                    "result": "Replacement finished.",
                },
                "complete-replacement",
            )
        if step == 4:
            return self._tool_response("mark_all_complete", {"summary": "Replacement plan completed."}, "complete-goal")
        if step == 5:
            return self._content_response("Replacement plan completed.")

        raise AssertionError("Task loop made an unexpected model call")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next(kwargs["messages"])

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next(kwargs["messages"])

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next(kwargs["messages"])

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next(kwargs["messages"])

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def _task_tools(
    task_list: TaskList,
    *,
    members: list[Agent] | None = None,
    async_mode: bool = False,
    stream_events: bool = False,
    store_events: bool = False,
    run_response: TeamRunOutput | None = None,
) -> tuple[dict[str, Function], dict[str, Any], TeamSession]:
    session_state: dict[str, Any] = {}
    save_task_list(session_state, task_list)
    session = TeamSession(session_id="task-session")
    team = Team(
        id="task-team",
        name="Task Team",
        members=members or [],
        mode=TeamMode.tasks,
        store_events=store_events,
        telemetry=False,
    )
    task_run_response = run_response or TeamRunOutput(session_id=session.session_id)
    tools = _get_task_management_tools(
        team=team,
        task_list=task_list,
        run_response=task_run_response,
        run_context=RunContext(run_id="task-run", session_id=session.session_id, session_state=session_state),
        session=session,
        team_run_context={},
        async_mode=async_mode,
        stream_events=stream_events,
    )
    return {tool.name: tool for tool in tools}, session_state, session


def _run_generator_tool(tool: Function, **kwargs: Any) -> list[Any]:
    assert tool.entrypoint is not None
    return list(tool.entrypoint(**kwargs))


class TestDependencyContext:
    """Dependency results must reach the real execute_task member input."""

    @staticmethod
    def _task_list() -> tuple[TaskList, str]:
        task_list = TaskList()
        research = task_list.create_task("Research auth")
        task_list.update_task(
            research.id,
            status=TaskStatus.completed,
            result="The expiry check is missing in auth.py:42.",
        )
        implementation = task_list.create_task(
            "Fix auth",
            description="Implement the expiry check.",
            dependencies=[research.id],
        )
        return task_list, implementation.id

    def test_execute_task_passes_dependency_results_to_member_sync(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}
        member = Agent(id="worker", name="Worker", telemetry=False)

        def fake_run(*, input: Any, **kwargs: Any) -> RunOutput:
            captured["input"] = input
            return RunOutput(
                run_id="member-sync",
                agent_id=member.id,
                session_id="task-session",
                content="Implemented.",
                status=RunStatus.completed,
            )

        monkeypatch.setattr(member, "run", fake_run)
        task_list, task_id = self._task_list()
        tools, session_state, _ = _task_tools(task_list, members=[member])

        output = _run_generator_tool(tools["execute_task"], task_id=task_id, member_id="worker")

        assert output[-1] == f"Task [{task_id}] completed. Result: Implemented."
        assert captured["input"] == (
            '<dependency_results>\nTask "Research auth" result:\n'
            "The expiry check is missing in auth.py:42.\n</dependency_results>\n\n"
            "Implement the expiry check."
        )
        assert load_task_list(session_state).get_task(task_id).status == TaskStatus.completed  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_execute_task_passes_dependency_results_to_member_async(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}
        member = Agent(id="worker", name="Worker", telemetry=False)

        async def fake_arun(*, input: Any, **kwargs: Any) -> RunOutput:
            captured["input"] = input
            return RunOutput(
                run_id="member-async",
                agent_id=member.id,
                session_id="task-session",
                content="Implemented async.",
                status=RunStatus.completed,
            )

        monkeypatch.setattr(member, "arun", fake_arun)
        task_list, task_id = self._task_list()
        tools, session_state, _ = _task_tools(task_list, members=[member], async_mode=True)
        execute_task = tools["execute_task"]
        assert execute_task.entrypoint is not None

        output = [item async for item in execute_task.entrypoint(task_id=task_id, member_id="worker")]

        assert output[-1] == f"Task [{task_id}] completed. Result: Implemented async."
        assert '<dependency_results>\nTask "Research auth" result:\n' in captured["input"]
        assert "The expiry check is missing in auth.py:42." in captured["input"]
        assert captured["input"].endswith("Implement the expiry check.")
        assert load_task_list(session_state).get_task(task_id).status == TaskStatus.completed  # type: ignore[union-attr]

    def test_execute_task_emits_derived_unblocking_updates_sync(self, monkeypatch: pytest.MonkeyPatch):
        member = Agent(id="worker", name="Worker", telemetry=False)

        def fake_run(**kwargs: Any) -> RunOutput:
            return RunOutput(
                run_id="member-sync-events",
                agent_id=member.id,
                session_id="task-session",
                content="Implemented.",
                status=RunStatus.completed,
            )

        monkeypatch.setattr(member, "run", fake_run)
        task_list = TaskList()
        root = task_list.create_task("Root", assignee="worker")
        child = task_list.create_task("Child", dependencies=[root.id])
        run_response = TeamRunOutput(session_id="task-session")
        tools, _, _ = _task_tools(
            task_list,
            members=[member],
            stream_events=True,
            store_events=True,
            run_response=run_response,
        )

        output = _run_generator_tool(tools["execute_task"], task_id=root.id, member_id="worker")

        live_events = [event for event in output if isinstance(event, TaskUpdatedEvent)]
        stored_events = [event for event in (run_response.events or []) if isinstance(event, TaskUpdatedEvent)]
        assert [(event.task_id, event.previous_status, event.status) for event in live_events] == [
            (root.id, "pending", "in_progress"),
            (root.id, "in_progress", "completed"),
            (child.id, "blocked", "pending"),
        ]
        assert all(live is stored for live, stored in zip(live_events, stored_events))

    @pytest.mark.asyncio
    async def test_execute_task_emits_derived_unblocking_updates_async(self, monkeypatch: pytest.MonkeyPatch):
        member = Agent(id="worker", name="Worker", telemetry=False)

        async def fake_arun(**kwargs: Any) -> RunOutput:
            return RunOutput(
                run_id="member-async-events",
                agent_id=member.id,
                session_id="task-session",
                content="Implemented async.",
                status=RunStatus.completed,
            )

        monkeypatch.setattr(member, "arun", fake_arun)
        task_list = TaskList()
        root = task_list.create_task("Root", assignee="worker")
        child = task_list.create_task("Child", dependencies=[root.id])
        run_response = TeamRunOutput(session_id="task-session")
        tools, _, _ = _task_tools(
            task_list,
            members=[member],
            async_mode=True,
            stream_events=True,
            store_events=True,
            run_response=run_response,
        )
        execute_task = tools["execute_task"]
        assert execute_task.entrypoint is not None

        output = [item async for item in execute_task.entrypoint(task_id=root.id, member_id="worker")]

        live_events = [event for event in output if isinstance(event, TaskUpdatedEvent)]
        stored_events = [event for event in (run_response.events or []) if isinstance(event, TaskUpdatedEvent)]
        assert [(event.task_id, event.previous_status, event.status) for event in live_events] == [
            (root.id, "pending", "in_progress"),
            (root.id, "in_progress", "completed"),
            (child.id, "blocked", "pending"),
        ]
        assert all(live is stored for live, stored in zip(live_events, stored_events))


class TestTaskStatePersistence:
    """Rebuilding tasks-mode tools must load, rather than reset, session state."""

    def test_new_tool_construction_keeps_existing_tasks(self):
        from agno.team._tools import _determine_tools_for_model

        session_state: dict[str, Any] = {}
        run_context = RunContext(run_id="run-1", session_id="session-1", session_state=session_state)
        run_response = TeamRunOutput(run_id="run-1", session_id="session-1")
        session = TeamSession(session_id="session-1")
        team = Team(id="team-1", name="Tasks", members=[], mode=TeamMode.tasks, telemetry=False)
        model = MagicMock()
        model.supports_native_structured_outputs = False

        first_tools = _determine_tools_for_model(
            team=team,
            model=model,
            run_response=run_response,
            run_context=run_context,
            team_run_context={},
            session=session,
            check_mcp_tools=False,
        )
        first_by_name = {tool.name: tool for tool in first_tools if isinstance(tool, Function)}
        _run_generator_tool(first_by_name["create_task"], title="Persistent task")

        second_tools = _determine_tools_for_model(
            team=team,
            model=model,
            run_response=run_response,
            run_context=run_context,
            team_run_context={},
            session=session,
            check_mcp_tools=False,
        )
        second_by_name = {tool.name: tool for tool in second_tools if isinstance(tool, Function)}
        assert second_by_name["list_tasks"].entrypoint is not None

        assert "Persistent task" in second_by_name["list_tasks"].entrypoint()
        persisted = load_task_list(session_state)
        assert [task.title for task in persisted.tasks] == ["Persistent task"]

    def test_cached_session_preserves_tasks_and_allows_a_new_goal(self):
        model = _MultiRunTaskModel()
        team = Team(
            id="multi-run-team",
            name="Multi-run Tasks",
            members=[],
            mode=TeamMode.tasks,
            model=model,
            session_id="multi-run-session",
            cache_session=True,
            max_iterations=3,
            telemetry=False,
        )

        first_response = team.run("Complete the first goal")
        first_task_list = load_task_list(first_response.session_state)
        assert [task.title for task in first_task_list.tasks] == ["First task"]
        assert first_task_list.goal_complete is True
        assert first_task_list.completion_summary == "First goal complete"

        second_response = team.run("Complete a follow-up goal")
        second_task_list = load_task_list(second_response.session_state)

        assert model.response_count == 3
        assert [task.title for task in second_task_list.tasks] == ["First task", "Second task"]
        assert [task.status for task in second_task_list.tasks] == [TaskStatus.completed, TaskStatus.completed]
        assert second_task_list.goal_complete is True
        assert second_task_list.completion_summary == "Second goal complete"

    @pytest.mark.asyncio
    async def test_async_cached_session_preserves_tasks_and_executes_a_new_goal(self):
        model = _MultiRunTaskModel()
        team = Team(
            id="async-multi-run-team",
            name="Async Multi-run Tasks",
            members=[],
            mode=TeamMode.tasks,
            model=model,
            session_id="async-multi-run-session",
            cache_session=True,
            max_iterations=3,
            telemetry=False,
        )

        first_response = await team.arun("Complete the first goal")
        assert first_response.content == "First goal complete."
        first_run_action_count = len(model.tool_actions)

        second_response = await team.arun("Complete a follow-up goal")

        assert second_response.content == "Second goal complete."
        assert model.response_count == 3
        assert model.second_run_task_summary is not None
        assert "First task" in model.second_run_task_summary
        assert "COMPLETED" in model.second_run_task_summary
        assert model.tool_actions[first_run_action_count:] == [
            ("list_tasks", ""),
            ("create_task", "Second task"),
            ("update_task_status", "Second result"),
            ("mark_all_complete", "Second goal complete"),
        ]

        assert team._cached_session is not None
        cached_session_state = (team._cached_session.session_data or {}).get("session_state")
        cached_task_list = load_task_list(cached_session_state)
        assert [task.title for task in cached_task_list.tasks] == ["First task", "Second task"]
        assert [task.status for task in cached_task_list.tasks] == [TaskStatus.completed, TaskStatus.completed]


def _cancellation_replan_team() -> tuple[Team, _CancellationReplanModel, dict[str, Any]]:
    session_state: dict[str, Any] = {}
    task_list = TaskList()
    obsolete_task = task_list.create_task("Obsolete work")
    save_task_list(session_state, task_list)
    model = _CancellationReplanModel(obsolete_task.id)
    team = Team(
        id="cancellation-replan-team",
        name="Cancellation Replan Team",
        members=[],
        mode=TeamMode.tasks,
        model=model,
        max_iterations=2,
        telemetry=False,
    )
    return team, model, session_state


def _assert_cancellation_replan_completed(
    model: _CancellationReplanModel,
    session_state: dict[str, Any],
) -> None:
    assert model.invoke_count == 6, "an all-cancelled first iteration incorrectly terminated the task loop"
    assert model.replacement_task_id is not None

    task_list = load_task_list(session_state)
    assert [(task.title, task.status, task.result) for task in task_list.tasks] == [
        ("Obsolete work", TaskStatus.cancelled, "Cancelled: Superseded by a better plan"),
        ("Replacement work", TaskStatus.completed, "Replacement finished."),
    ]
    assert task_list.goal_complete is True
    assert task_list.completion_summary == "Replacement plan completed."


def _assert_two_paired_task_iterations(events: list[Any]) -> None:
    iteration_started = [event for event in events if isinstance(event, TaskIterationStartedEvent)]
    iteration_completed = [event for event in events if isinstance(event, TaskIterationCompletedEvent)]

    assert [event.iteration for event in iteration_started] == [1, 2]
    assert [event.iteration for event in iteration_completed] == [1, 2]
    assert [event.run_id for event in iteration_started] == [event.run_id for event in iteration_completed]


class TestCancellationReplanning:
    """Cancelling obsolete work must leave the leader an iteration to replace it."""

    def test_sync_all_cancelled_plan_continues_to_replacement(self):
        team, model, session_state = _cancellation_replan_team()

        response = team.run("Replace the obsolete work", session_state=session_state)

        _assert_cancellation_replan_completed(model, response.session_state)

    @pytest.mark.asyncio
    async def test_async_all_cancelled_plan_continues_to_replacement(self):
        team, model, session_state = _cancellation_replan_team()

        response = await team.arun("Replace the obsolete work", session_state=session_state)

        _assert_cancellation_replan_completed(model, response.session_state)

    def test_sync_stream_all_cancelled_plan_continues_with_paired_iteration_events(self):
        team, model, session_state = _cancellation_replan_team()

        events = list(
            team.run(
                "Replace the obsolete work",
                stream=True,
                stream_events=True,
                yield_run_output=True,
                session_state=session_state,
            )
        )

        _assert_two_paired_task_iterations(events)
        run_outputs = [event for event in events if isinstance(event, TeamRunOutput)]
        assert len(run_outputs) == 1
        _assert_cancellation_replan_completed(model, run_outputs[0].session_state)

    @pytest.mark.asyncio
    async def test_async_stream_all_cancelled_plan_continues_with_paired_iteration_events(self):
        team, model, session_state = _cancellation_replan_team()

        events = [
            event
            async for event in team.arun(
                "Replace the obsolete work",
                stream=True,
                stream_events=True,
                yield_run_output=True,
                session_state=session_state,
            )
        ]

        _assert_two_paired_task_iterations(events)
        run_outputs = [event for event in events if isinstance(event, TeamRunOutput)]
        assert len(run_outputs) == 1
        _assert_cancellation_replan_completed(model, run_outputs[0].session_state)


class TestConfigurableTruncation:
    def test_default_and_custom_result_limits(self):
        task_list = TaskList()
        task = task_list.create_task("Test")
        task_list.update_task(task.id, status=TaskStatus.completed, result="x" * 1500)

        default_summary = task_list.get_summary_string()
        custom_summary = task_list.get_summary_string(result_limit=1000)

        assert "x" * 200 + "..." in default_summary
        assert "x" * 201 not in default_summary
        assert "x" * 1000 + "..." in custom_summary
        assert "x" * 1001 not in custom_summary

    def test_team_default_limit_is_500(self):
        assert Team(name="test", members=[]).task_result_summary_limit == 500


class TestEditTaskTool:
    def test_edit_task_entrypoint_persists_all_supported_changes(self):
        task_list = TaskList()
        task = task_list.create_task("Original", description="Old", assignee="worker-a")
        tools, session_state, _ = _task_tools(task_list)

        output = _run_generator_tool(
            tools["edit_task"],
            task_id=task.id,
            title="Updated",
            description="New",
            assignee="worker-b",
        )

        assert output == [f"Task [{task.id}] updated: title='Updated', description updated, assignee='worker-b'."]
        persisted = load_task_list(session_state).get_task(task.id)
        assert persisted is not None
        assert (persisted.title, persisted.description, persisted.assignee) == ("Updated", "New", "worker-b")

    def test_edit_task_rejects_normalized_active_title_conflict_atomically(self):
        task_list = TaskList()
        existing = task_list.create_task("Research")
        draft = task_list.create_task("Draft", description="Original", assignee="worker-a")
        run_response = TeamRunOutput(session_id="task-session")
        tools, session_state, _ = _task_tools(
            task_list,
            stream_events=True,
            store_events=True,
            run_response=run_response,
        )

        output = _run_generator_tool(
            tools["edit_task"],
            task_id=draft.id,
            title=" research ",
            description="Must not change",
            assignee="worker-b",
        )

        assert output == [
            f"Task already exists: [{existing.id}] Research (status: pending). Use this task instead of creating a duplicate."
        ]
        persisted = load_task_list(session_state).get_task(draft.id)
        assert persisted is not None
        assert (persisted.title, persisted.description, persisted.assignee) == ("Draft", "Original", "worker-a")
        assert not [event for event in (run_response.events or []) if isinstance(event, TaskUpdatedEvent)]

    def test_edit_task_allows_normalized_self_title_and_cancelled_duplicate(self):
        task_list = TaskList()
        current = task_list.create_task("Research")
        cancelled = task_list.create_task("Archived title")
        task_list.update_task(cancelled.id, status=TaskStatus.cancelled, result="Archived")
        tools, session_state, _ = _task_tools(task_list)

        self_output = _run_generator_tool(tools["edit_task"], task_id=current.id, title=" research ")
        cancelled_output = _run_generator_tool(tools["edit_task"], task_id=current.id, title=" archived TITLE ")

        assert self_output == [f"Task [{current.id}] updated: title=' research '."]
        assert cancelled_output == [f"Task [{current.id}] updated: title=' archived TITLE '."]
        assert load_task_list(session_state).get_task(current.id).title == " archived TITLE "  # type: ignore[union-attr]

    @pytest.mark.parametrize(
        "status", [TaskStatus.in_progress, TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled]
    )
    def test_edit_task_entrypoint_rejects_non_editable_statuses(self, status: TaskStatus):
        task_list = TaskList()
        task = task_list.create_task("Guarded")
        task_list.update_task(task.id, status=status, result="Existing result")
        tools, session_state, _ = _task_tools(task_list)

        output = _run_generator_tool(tools["edit_task"], task_id=task.id, title="Must not change")

        assert output == [
            f"Cannot edit task [{task.id}] with status '{status.value}'. Only pending or blocked tasks can be edited."
        ]
        assert load_task_list(session_state).get_task(task.id).title == "Guarded"  # type: ignore[union-attr]

    def test_edit_task_entrypoint_rejects_missing_task_and_empty_edit(self):
        task_list = TaskList()
        task = task_list.create_task("Original")
        tools, _, _ = _task_tools(task_list)

        assert _run_generator_tool(tools["edit_task"], task_id="missing", title="Nope") == [
            "Task with ID 'missing' not found."
        ]
        assert _run_generator_tool(tools["edit_task"], task_id=task.id) == [
            f"No changes provided for task [{task.id}]."
        ]


class TestCancelTaskTool:
    def test_cancel_task_entrypoint_cascades_cancelled_state_and_persists(self):
        task_list = TaskList()
        root = task_list.create_task("Root")
        child = task_list.create_task("Child", dependencies=[root.id])
        grandchild = task_list.create_task("Grandchild", dependencies=[child.id])
        tools, session_state, _ = _task_tools(task_list)

        output = _run_generator_tool(tools["cancel_task"], task_id=root.id, reason="Replanned")

        assert output == [f"Task [{root.id}] 'Root' cancelled."]
        persisted = load_task_list(session_state)
        assert [persisted.get_task(task.id).status for task in (root, child, grandchild)] == [  # type: ignore[union-attr]
            TaskStatus.cancelled,
            TaskStatus.cancelled,
            TaskStatus.cancelled,
        ]
        assert persisted.get_task(root.id).result == "Cancelled: Replanned"  # type: ignore[union-attr]
        assert persisted.get_task(child.id).result == (  # type: ignore[union-attr]
            "Automatically cancelled: a dependency was cancelled."
        )
        assert persisted.get_task(grandchild.id).result == (  # type: ignore[union-attr]
            "Automatically cancelled: a dependency was cancelled."
        )
        assert persisted.all_terminal()

    @staticmethod
    def _assert_live_and_stored_updates(
        output: list[Any],
        run_response: TeamRunOutput,
        expected: list[tuple[str, str, str, str | None]],
    ) -> None:
        live_events = [event for event in output if isinstance(event, TaskUpdatedEvent)]
        stored_events = [event for event in (run_response.events or []) if isinstance(event, TaskUpdatedEvent)]
        assert [(event.task_id, event.previous_status, event.status, event.result) for event in live_events] == expected
        assert len(stored_events) == len(live_events)
        assert all(live is stored for live, stored in zip(live_events, stored_events))

    def test_cancel_task_emits_and_stores_every_derived_cascade_update(self):
        task_list = TaskList()
        root = task_list.create_task("Root")
        child = task_list.create_task("Child", dependencies=[root.id])
        grandchild = task_list.create_task("Grandchild", dependencies=[child.id])
        run_response = TeamRunOutput(session_id="task-session")
        tools, _, _ = _task_tools(
            task_list,
            stream_events=True,
            store_events=True,
            run_response=run_response,
        )

        output = _run_generator_tool(tools["cancel_task"], task_id=root.id, reason="Replanned")

        self._assert_live_and_stored_updates(
            output,
            run_response,
            [
                (root.id, "pending", "cancelled", "Cancelled: Replanned"),
                (child.id, "blocked", "cancelled", "Automatically cancelled: a dependency was cancelled."),
                (
                    grandchild.id,
                    "blocked",
                    "cancelled",
                    "Automatically cancelled: a dependency was cancelled.",
                ),
            ],
        )

    def test_update_status_emits_failed_cascade_and_completed_unblocking_updates(self):
        failed_list = TaskList()
        failed_root = failed_list.create_task("Failed root")
        failed_child = failed_list.create_task("Failed child", dependencies=[failed_root.id])
        failed_grandchild = failed_list.create_task("Failed grandchild", dependencies=[failed_child.id])
        failed_response = TeamRunOutput(session_id="failed-session")
        failed_tools, _, _ = _task_tools(
            failed_list,
            stream_events=True,
            store_events=True,
            run_response=failed_response,
        )

        failed_output = _run_generator_tool(
            failed_tools["update_task_status"],
            task_id=failed_root.id,
            status="failed",
            result="Root failed",
        )

        self._assert_live_and_stored_updates(
            failed_output,
            failed_response,
            [
                (failed_root.id, "pending", "failed", "Root failed"),
                (failed_child.id, "blocked", "failed", "Automatically failed: a dependency failed."),
                (
                    failed_grandchild.id,
                    "blocked",
                    "failed",
                    "Automatically failed: a dependency failed.",
                ),
            ],
        )

        completed_list = TaskList()
        completed_root = completed_list.create_task("Completed root")
        unblocked_child = completed_list.create_task("Unblocked child", dependencies=[completed_root.id])
        completed_response = TeamRunOutput(session_id="completed-session")
        completed_tools, _, _ = _task_tools(
            completed_list,
            stream_events=True,
            store_events=True,
            run_response=completed_response,
        )

        completed_output = _run_generator_tool(
            completed_tools["update_task_status"],
            task_id=completed_root.id,
            status="completed",
            result="Done",
        )

        self._assert_live_and_stored_updates(
            completed_output,
            completed_response,
            [
                (completed_root.id, "pending", "completed", "Done"),
                (unblocked_child.id, "blocked", "pending", None),
            ],
        )

    @pytest.mark.parametrize(
        "status", [TaskStatus.in_progress, TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled]
    )
    def test_cancel_task_entrypoint_rejects_non_cancellable_statuses(self, status: TaskStatus):
        task_list = TaskList()
        task = task_list.create_task("Guarded")
        task_list.update_task(task.id, status=status, result="Existing result")
        tools, session_state, _ = _task_tools(task_list)

        output = _run_generator_tool(tools["cancel_task"], task_id=task.id, reason="Nope")

        assert output == [
            f"Cannot cancel task [{task.id}] with status '{status.value}'. Only pending or blocked tasks can be cancelled."
        ]
        persisted = load_task_list(session_state).get_task(task.id)
        assert persisted is not None
        assert (persisted.status, persisted.result) == (status, "Existing result")

    def test_cancel_task_entrypoint_rejects_missing_task(self):
        tools, _, _ = _task_tools(TaskList())

        assert _run_generator_tool(tools["cancel_task"], task_id="missing") == ["Task with ID 'missing' not found."]

    def test_cancelled_task_does_not_block_a_same_title_replacement(self):
        task_list = TaskList()
        cancelled = task_list.create_task("Draft report")
        tools, session_state, _ = _task_tools(task_list)
        _run_generator_tool(tools["cancel_task"], task_id=cancelled.id, reason="Replace the approach")

        output = _run_generator_tool(tools["create_task"], title="Draft report")

        assert output[-1].startswith("Task created: [")
        persisted = load_task_list(session_state)
        assert [task.title for task in persisted.tasks] == ["Draft report", "Draft report"]
        assert [task.status for task in persisted.tasks] == [TaskStatus.cancelled, TaskStatus.pending]
        assert persisted.tasks[0].id != persisted.tasks[1].id

    def test_update_status_cannot_bypass_cancel_task_guard(self):
        task_list = TaskList()
        task = task_list.create_task("Guarded")
        tools, session_state, _ = _task_tools(task_list)

        output = _run_generator_tool(
            tools["update_task_status"],
            task_id=task.id,
            status=TaskStatus.cancelled.value,
        )

        assert output == [
            "Cannot manually set status to 'cancelled'. Use cancel_task for cancellation; "
            "blocked status is managed automatically."
        ]
        assert load_task_list(session_state).get_task(task.id).status == TaskStatus.pending  # type: ignore[union-attr]

    @pytest.mark.parametrize(
        "new_status",
        [TaskStatus.pending, TaskStatus.in_progress, TaskStatus.completed, TaskStatus.failed],
    )
    def test_update_status_rejects_reopening_cancelled_task_and_preserves_graph(self, new_status: TaskStatus):
        task_list = TaskList()
        root = task_list.create_task("Root")
        child = task_list.create_task("Child", dependencies=[root.id])
        task_list.create_task("Grandchild", dependencies=[child.id])
        tools, session_state, _ = _task_tools(task_list)
        _run_generator_tool(tools["cancel_task"], task_id=root.id, reason="Replanned")
        cancelled_graph = load_task_list(session_state).to_dict()

        output = _run_generator_tool(
            tools["update_task_status"],
            task_id=root.id,
            status=new_status.value,
            result="Stale replacement result",
        )

        assert output == [
            f"Cannot update task [{root.id}] with status 'cancelled'. Cancelled tasks cannot be reopened."
        ]
        assert load_task_list(session_state).to_dict() == cancelled_graph
