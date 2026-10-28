"""Unit tests for the A2A interface's stream_run_events_to_task, build_agent_card and A2ATaskStore.

Regression coverage for: RunCompletedEvent.metadata (e.g. sources, refetch_model
set by a caller's post-processing step) must ride the terminal status-update
event, which the A2A client reads as the run's out-of-band metadata.
"""

from datetime import datetime
from types import SimpleNamespace
from typing import AsyncIterator, List, Union
from unittest.mock import patch

import pytest
from a2a.server.context import ServerCallContext
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    ListTasksRequest,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from google.protobuf.json_format import MessageToDict

from agno.agent import Agent
from agno.os.interfaces.a2a.agent_card import build_agent_card
from agno.os.interfaces.a2a.context import A2AUser
from agno.os.interfaces.a2a.executor import A2AExecutor
from agno.os.interfaces.a2a.streaming import stream_run_events_to_task
from agno.os.interfaces.a2a.task_store import A2ATaskStore
from agno.os.interfaces.a2a.utils import map_run_output_to_a2a_task
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunErrorEvent, RunOutput, RunStartedEvent
from agno.run.base import RunStatus
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent


async def _agent_stream(
    *events: Union[RunStartedEvent, RunContentEvent, RunCompletedEvent],
) -> AsyncIterator:
    for event in events:
        yield event


class _RecordingEventQueue:
    """Collects the events a TaskUpdater enqueues."""

    def __init__(self):
        self.events: List = []

    async def enqueue_event(self, event) -> None:
        self.events.append(event)


def _final_status_update(events):
    """Return the terminal status-update event."""
    finals = [
        e for e in events if isinstance(e, TaskStatusUpdateEvent) and e.status.state != TaskState.TASK_STATE_WORKING
    ]
    assert len(finals) == 1
    return finals[0]


def _call_context(user_id):
    """The call context of an authenticated caller."""
    return ServerCallContext(user=A2AUser(user_id=user_id, is_authenticated=True))


class TestStreamRunEventsToTaskMetadata:
    @pytest.mark.asyncio
    async def test_run_completed_metadata_rides_terminal_status_update(self):
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunContentEvent(content="Hello", run_id="run-1", session_id="ctx-1"),
            RunCompletedEvent(
                content="Hello",
                run_id="run-1",
                session_id="ctx-1",
                metadata={"sources": {"llm_sources": []}, "refetch_model": True},
            ),
        )

        event_queue = _RecordingEventQueue()
        await stream_run_events_to_task(stream, TaskUpdater(event_queue, "run-1", "ctx-1"))

        final = _final_status_update(event_queue.events)
        assert final.status.state == TaskState.TASK_STATE_COMPLETED
        assert MessageToDict(final.metadata) == {"sources": {"llm_sources": []}, "refetch_model": True}

    @pytest.mark.asyncio
    async def test_run_completed_without_metadata_omits_status_metadata_field(self):
        """No metadata set means the terminal status-update carries no metadata,
        not an empty dict."""
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunContentEvent(content="Hi", run_id="run-1", session_id="ctx-1"),
            RunCompletedEvent(content="Hi", run_id="run-1", session_id="ctx-1"),
        )

        event_queue = _RecordingEventQueue()
        await stream_run_events_to_task(stream, TaskUpdater(event_queue, "run-1", "ctx-1"))

        final = _final_status_update(event_queue.events)
        assert not final.HasField("metadata")


class TestStreamRunEventsToTask:
    @pytest.mark.asyncio
    async def test_content_streams_as_one_artifact_closed_by_the_full_response(self):
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunContentEvent(content="Hel", run_id="run-1", session_id="ctx-1"),
            RunContentEvent(content="lo", run_id="run-1", session_id="ctx-1"),
            RunCompletedEvent(content="Hello", run_id="run-1", session_id="ctx-1"),
        )

        event_queue = _RecordingEventQueue()
        await stream_run_events_to_task(stream, TaskUpdater(event_queue, "run-1", "ctx-1"))

        artifacts = [e for e in event_queue.events if isinstance(e, TaskArtifactUpdateEvent)]
        assert len({e.artifact.artifact_id for e in artifacts}) == 1
        assert [(e.artifact.parts[0].text, e.append, e.last_chunk) for e in artifacts] == [
            ("Hel", False, False),
            ("lo", True, False),
            ("Hello", False, True),
        ]

    @pytest.mark.asyncio
    async def test_member_error_does_not_fail_the_team_task(self):
        """A member run that errors inside a team run must not end the team's task as failed."""
        stream = _agent_stream(
            TeamRunStartedEvent(run_id="team-run", session_id="ctx-1"),
            RunStartedEvent(run_id="member-run", session_id="ctx-1"),
            RunErrorEvent(content="member failed", run_id="member-run", session_id="ctx-1"),
            TeamRunCompletedEvent(content="Recovered", run_id="team-run", session_id="ctx-1"),
        )

        event_queue = _RecordingEventQueue()
        await stream_run_events_to_task(stream, TaskUpdater(event_queue, "team-run", "ctx-1"))

        final = _final_status_update(event_queue.events)
        assert final.status.state == TaskState.TASK_STATE_COMPLETED

    @pytest.mark.asyncio
    async def test_run_error_marks_task_failed(self):
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunErrorEvent(content="model unavailable", run_id="run-1", session_id="ctx-1"),
        )

        event_queue = _RecordingEventQueue()
        await stream_run_events_to_task(stream, TaskUpdater(event_queue, "run-1", "ctx-1"))

        final = _final_status_update(event_queue.events)
        assert final.status.state == TaskState.TASK_STATE_FAILED
        assert final.status.message.parts[0].text == "model unavailable"


class TestBuildAgentCard:
    def test_card_describes_the_agent_and_its_endpoint(self):
        agent = Agent(id="support", name="Support", description="Answers support questions")

        card = build_agent_card(agent, url="http://localhost:7777/a2a/agents/support")

        assert card.name == "Support"
        assert card.description == "Answers support questions"
        assert card.capabilities.streaming is True
        assert [(i.url, i.protocol_binding, i.protocol_version) for i in card.supported_interfaces] == [
            ("http://localhost:7777/a2a/agents/support", "JSONRPC", "1.0"),
            ("http://localhost:7777/a2a/agents/support", "JSONRPC", "0.3"),
        ]
        assert [(s.id, s.name, list(s.examples)) for s in card.skills] == [("support", "Support", [])]
        assert list(card.default_output_modes) == ["text/plain"]

    def test_card_name_falls_back_to_the_agent_id(self):
        agent = Agent(id="support")

        card = build_agent_card(agent, url="http://localhost:7777/a2a/agents/support", enable_v0_3_compat=False)

        assert card.name == "support"
        assert [i.protocol_version for i in card.supported_interfaces] == ["1.0"]


class TestA2ATaskStore:
    @pytest.mark.asyncio
    async def test_task_keeps_its_owner_when_another_caller_saves_it(self):
        """An admin acting on a task (e.g. cancelling it) must not take it over from its owner."""
        task_store = A2ATaskStore(entity_type="agent", entity=Agent(id="support"))
        task = Task(id="task-1", context_id="ctx-1", status=TaskStatus(state=TaskState.TASK_STATE_WORKING))

        await task_store.save(task, _call_context("alice"))
        await task_store.save(task, _call_context("admin"))

        assert await task_store.get("task-1", _call_context("alice")) is not None
        assert await task_store.get("task-1", _call_context("admin")) is None

    @pytest.mark.asyncio
    async def test_list_filters_by_status_and_pages(self):
        task_store = A2ATaskStore(entity_type="agent", entity=Agent(id="support"))
        context = _call_context("alice")
        for task_id in ("task-1", "task-2", "task-3"):
            await task_store.save(
                Task(id=task_id, context_id="ctx-1", status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED)), context
            )
        await task_store.save(
            Task(id="task-4", context_id="ctx-1", status=TaskStatus(state=TaskState.TASK_STATE_WORKING)), context
        )

        completed = await task_store.list(ListTasksRequest(status=TaskState.TASK_STATE_COMPLETED, page_size=2), context)
        assert completed.total_size == 3
        assert len(completed.tasks) == 2

        next_page = await task_store.list(
            ListTasksRequest(status=TaskState.TASK_STATE_COMPLETED, page_size=2, page_token=completed.next_page_token),
            context,
        )
        assert len(next_page.tasks) == 1
        assert not {task.id for task in completed.tasks} & {task.id for task in next_page.tasks}


class TestRunMetadataOnTask:
    @pytest.mark.asyncio
    async def test_completion_metadata_that_is_not_json_still_completes_the_task(self):
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunCompletedEvent(
                content="Hi",
                run_id="run-1",
                session_id="ctx-1",
                metadata={"requested_at": datetime(2026, 1, 1)},
            ),
        )

        event_queue = _RecordingEventQueue()
        await stream_run_events_to_task(stream, TaskUpdater(event_queue, "run-1", "ctx-1"))

        final = _final_status_update(event_queue.events)
        assert final.status.state == TaskState.TASK_STATE_COMPLETED
        assert MessageToDict(final.metadata) == {"requested_at": "2026-01-01T00:00:00"}

    def test_stored_run_metadata_does_not_override_the_run_user(self):
        run_output = RunOutput(
            run_id="run-1",
            session_id="ctx-1",
            agent_id="agent-1",
            user_id="alice",
            status=RunStatus.completed,
            content="Hi",
            metadata={"userId": "mallory", "requested_at": datetime(2026, 1, 1)},
        )

        task = map_run_output_to_a2a_task(run_output)

        metadata = MessageToDict(task.metadata)
        assert metadata["userId"] == "alice"
        assert metadata["requested_at"] == "2026-01-01T00:00:00"


class TestExecutorFailure:
    @pytest.mark.asyncio
    async def test_a_failed_final_status_update_still_ends_the_task_failed(self):
        async def _empty_stream(**kwargs):
            return
            yield

        async def _fail_on_final_status(event_stream, updater, user_id=None):
            # The updater marks itself terminal before the event is built, so the event never goes out
            await updater.update_status(TaskState.TASK_STATE_COMPLETED, metadata={"bad": object()})

        executor = A2AExecutor(entity_type="agent", entity_id="agent-1")
        context = SimpleNamespace(
            message=Message(message_id="m-1", role=Role.ROLE_USER, parts=[Part(text="Hi")]),
            task_id="run-1",
            context_id="ctx-1",
            current_task=None,
            call_context=SimpleNamespace(state={}),
        )
        event_queue = _RecordingEventQueue()
        with (
            patch.object(executor, "_get_entity", return_value=SimpleNamespace(arun=_empty_stream)),
            patch("agno.os.interfaces.a2a.executor.stream_run_events_to_task", _fail_on_final_status),
        ):
            await executor.execute(context, event_queue)

        final = _final_status_update(event_queue.events)
        assert final.status.state == TaskState.TASK_STATE_FAILED
