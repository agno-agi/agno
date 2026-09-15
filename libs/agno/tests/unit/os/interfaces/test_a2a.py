"""Unit tests for the A2A interface's stream_a2a_response function.

Regression coverage for: RunCompletedEvent.metadata (e.g. sources, refetch_model
set by a caller's post-processing step) must ride the terminal final=True
status-update event, which the A2A client reads as the run's out-of-band metadata.
"""

import json
from typing import AsyncIterator, Union

import pytest

from agno.os.interfaces.a2a.utils import stream_a2a_response
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunOutput,
    RunStartedEvent,
    VerificationCompletedEvent,
    VerificationStartedEvent,
)
from agno.run.base import RunStatus
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent
from agno.run.team import VerificationCompletedEvent as TeamVerificationCompletedEvent
from agno.run.workflow import WorkflowRunOutput
from agno.verifiers.types import Verdict, Verification


async def _agent_stream(
    *events: Union[RunStartedEvent, RunContentEvent, RunCompletedEvent],
) -> AsyncIterator:
    for event in events:
        yield event


def _parse_sse_events(raw: str):
    """Parse the "event: Name\\ndata: {...}\\n\\n" SSE blocks stream_a2a_response yields."""
    parsed = []
    for block in raw.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        for line in block.split("\n"):
            if line.startswith("data: "):
                parsed.append(json.loads(line[len("data: ") :]))
    return parsed


def _final_status_update(events):
    """Return the terminal final=True status-update event's result."""
    finals = [
        e["result"]
        for e in events
        if e.get("result", {}).get("kind") == "status-update" and e["result"].get("final") is True
    ]
    assert len(finals) == 1
    return finals[0]


class TestStreamA2AResponseMetadata:
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

        chunks = [chunk async for chunk in stream_a2a_response(stream, request_id="req-1")]
        events = _parse_sse_events("".join(chunks))

        final = _final_status_update(events)
        assert final["metadata"] == {"sources": {"llm_sources": []}, "refetch_model": True}

    @pytest.mark.asyncio
    async def test_run_completed_without_metadata_omits_status_metadata_field(self):
        """No metadata set means the terminal status-update's metadata field is
        omitted (exclude_none), not sent as an empty dict."""
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunContentEvent(content="Hi", run_id="run-1", session_id="ctx-1"),
            RunCompletedEvent(content="Hi", run_id="run-1", session_id="ctx-1"),
        )

        chunks = [chunk async for chunk in stream_a2a_response(stream, request_id="req-1")]
        events = _parse_sse_events("".join(chunks))

        final = _final_status_update(events)
        assert "metadata" not in final


class TestBlockingTaskForUnverifiedRun:
    """message:send maps an unverified run to a failed task that still carries its draft."""

    def test_unverified_run_maps_to_failed_task(self):
        from agno.os.interfaces.a2a.utils import map_run_output_to_a2a_task

        run_output = RunOutput(
            run_id="r-unv",
            session_id="s-1",
            content="draft answer",
            status=RunStatus.unverified,
            verification=Verification(status="unverified", stop_reason="exhausted"),
        )
        task = map_run_output_to_a2a_task(run_output)
        assert task.status.state.value == "failed"
        assert task.history[0].parts[0].root.text == "draft answer"


async def _collect(*events) -> list:
    chunks = [chunk async for chunk in stream_a2a_response(_agent_stream(*events), request_id="req-1")]
    return _parse_sse_events("".join(chunks))


def _tasks(events):
    return [e["result"] for e in events if e["result"].get("kind") == "task"]


def _working_updates(events):
    return [
        e["result"] for e in events if e["result"].get("kind") == "status-update" and e["result"].get("final") is False
    ]


def _task_id_of(result):
    # The a2a models serialize with field names by default but may carry
    # camelCase aliases; accept either so the assertion pins the value.
    return result.get("taskId", result.get("task_id"))


def _team_with_failed_member_events():
    return [
        TeamRunStartedEvent(run_id="team-1", session_id="sess-1"),
        RunStartedEvent(run_id="member-1", parent_run_id="team-1", session_id="sess-1"),
        VerificationCompletedEvent(
            run_id="member-1",
            parent_run_id="team-1",
            session_id="sess-1",
            attempt=2,
            max_attempts=2,
            passed=False,
            stop_reason="exhausted",
        ),
        TeamRunCompletedEvent(run_id="team-1", session_id="sess-1", content="team answer"),
    ]


class TestStreamA2AResponseVerification:
    @pytest.mark.asyncio
    async def test_verification_events_ride_as_working_updates(self):
        events = await _collect(
            RunStartedEvent(run_id="run-1", session_id="sess-1"),
            VerificationStartedEvent(run_id="run-1", session_id="sess-1", attempt=1, max_attempts=3),
            VerificationCompletedEvent(
                run_id="run-1", session_id="sess-1", attempt=1, max_attempts=3, passed=True, stop_reason="passed"
            ),
            RunCompletedEvent(run_id="run-1", session_id="sess-1", content="done"),
        )

        by_type = {(w.get("metadata") or {}).get("agno_event_type"): w for w in _working_updates(events)}
        assert "verification_started" in by_type
        completed = by_type["verification_completed"]["metadata"]
        assert (completed["passed"], completed["attempt"], completed["max_attempts"]) == (True, 1, 3)
        assert _final_status_update(events)["status"]["state"] == "completed"

    @pytest.mark.parametrize(
        "started, verified, completed",
        [
            (RunStartedEvent, VerificationCompletedEvent, RunCompletedEvent),
            (TeamRunStartedEvent, TeamVerificationCompletedEvent, TeamRunCompletedEvent),
        ],
        ids=["agent", "team"],
    )
    @pytest.mark.asyncio
    async def test_unverified_run_ends_failed(self, started, verified, completed):
        """The non-stream Task mapping reports UNVERIFIED as failed; the
        streaming path must agree."""
        events = await _collect(
            started(run_id="run-1", session_id="sess-1"),
            verified(
                run_id="run-1",
                session_id="sess-1",
                attempt=3,
                max_attempts=3,
                passed=False,
                stop_reason="exhausted",
                verdicts=[Verdict(passed=False, name="check", report="still failing")],
            ),
            completed(run_id="run-1", session_id="sess-1", content="claimed done", status="UNVERIFIED"),
        )

        assert _final_status_update(events)["status"]["state"] == "failed"
        (task,) = _tasks(events)
        assert task["status"]["state"] == "failed"

    @pytest.mark.asyncio
    async def test_workflow_unverified_run_ends_failed(self):
        """A workflow's gates are steps, so no verification event names the
        terminal state; the completed event's run output does."""
        from agno.run.workflow import WorkflowCompletedEvent, WorkflowStartedEvent

        run_output = WorkflowRunOutput(
            run_id="wf-1",
            session_id="sess-1",
            content="draft",
            status=RunStatus.unverified,
            verification=Verification(status="unverified", stop_reason="exhausted"),
        )
        events = await _collect(
            WorkflowStartedEvent(run_id="wf-1", session_id="sess-1"),
            WorkflowCompletedEvent(run_id="wf-1", session_id="sess-1", content="draft", run_output=run_output),
        )

        assert _final_status_update(events)["status"]["state"] == "failed"
        (task,) = _tasks(events)
        assert task["status"]["state"] == "failed"

    @pytest.mark.asyncio
    async def test_failed_member_does_not_fail_completed_team_run(self):
        """The task's lifecycle is scoped to the root run: a member's failed
        verification must not mark the completed team run failed, and the
        member's RunStarted must not replace the task identity. The member's
        verification outcome still flows as a working update marked with its origin."""
        events = await _collect(*_team_with_failed_member_events())

        final = _final_status_update(events)
        assert final["status"]["state"] == "completed"
        assert _task_id_of(final) == "team-1"
        (task,) = _tasks(events)
        assert (task["status"]["state"], task["id"]) == ("completed", "team-1")
        updates = [e["result"] for e in events if e["result"].get("kind") == "status-update"]
        assert all(_task_id_of(u) == "team-1" for u in updates)

        nested = [
            w
            for w in _working_updates(events)
            if (w.get("metadata") or {}).get("agno_event_type") == "verification_completed"
        ]
        assert len(nested) == 1
        assert nested[0]["metadata"]["passed"] is False
        assert nested[0]["metadata"]["origin_run_id"] == "member-1"
