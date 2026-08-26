"""RunStatus.unverified across the OS-layer surfaces.

Each test pins one surface that enumerates, filters, or maps run statuses:
the event-stream terminal sets (complete_run must not rewrite UNVERIFIED to
COMPLETED), the events-buffer reap list, the WebSocket/SSE resume tuples, the
job-queue ticket vocabulary, the scheduler poller's terminal set, the
RunSchema projections, and the MCP trimmed projection.
"""

import asyncio
import inspect
from time import time

import pytest

from agno.run.base import RunStatus
from agno.verifiers.types import Verification

# --- event streams: terminal sets -------------------------------------------


def test_in_memory_terminal_statuses_include_unverified():
    from agno.os.event_streams.in_memory import _TERMINAL_STATUSES

    assert RunStatus.unverified in _TERMINAL_STATUSES


def test_redis_terminal_statuses_include_unverified():
    # The redis backend has no top-level redis import, so the module's
    # terminal set is importable without the optional dependency.
    from agno.os.event_streams.redis import _TERMINAL_STATUSES

    assert RunStatus.unverified in _TERMINAL_STATUSES


# --- event streams: complete_run must not coerce UNVERIFIED -----------------


def _fresh_in_memory_stream():
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    return InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())


def test_in_memory_complete_run_keeps_unverified():
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("run-1", RunStatus.running)
        await stream.complete_run("run-1", RunStatus.unverified)
        return await stream.get_run_status("run-1")

    assert asyncio.run(scenario()) == RunStatus.unverified


def test_in_memory_complete_run_still_coerces_non_terminal():
    # The mark-terminal contract survives: a genuinely non-terminal argument
    # (a producer racing mid-transition) still coerces to COMPLETED.
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("run-2", RunStatus.running)
        await stream.complete_run("run-2", RunStatus.running)
        return await stream.get_run_status("run-2")

    assert asyncio.run(scenario()) == RunStatus.completed


def test_in_memory_tail_ends_on_unverified_run():
    # A tail attached to an already-unverified run must replay and end, not
    # idle against the live queue as if the run were still active.
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("run-3", RunStatus.running)
        await stream.complete_run("run-3", RunStatus.unverified)
        events = []
        async for item in stream.tail("run-3"):
            events.append(item)
        return events

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=5.0)) == []


# --- managers: EventsBuffer cleanup reaps unverified runs -------------------


def test_events_buffer_cleanup_reaps_unverified():
    from agno.os.managers import EventsBuffer

    buffer = EventsBuffer()
    buffer.register_run("run-unverified", RunStatus.running)
    buffer.set_run_completed("run-unverified", RunStatus.unverified)
    # Age the completion past the retention window, then reap.
    buffer.run_metadata["run-unverified"]["completed_at"] = time() - buffer.cleanup_interval - 1
    buffer.cleanup_runs()
    assert "run-unverified" not in buffer.run_metadata
    assert "run-unverified" not in buffer.events


def test_events_buffer_cleanup_keeps_running_runs():
    from agno.os.managers import EventsBuffer

    buffer = EventsBuffer()
    buffer.register_run("run-live", RunStatus.running)
    buffer.run_metadata["run-live"]["last_updated"] = time() - buffer.cleanup_interval - 1
    buffer.cleanup_runs()
    assert "run-live" in buffer.run_metadata


# --- routers: WebSocket/SSE resume tuples -----------------------------------


@pytest.mark.parametrize(
    "module_path, function_name",
    [
        ("agno.os.routers.agents.router", "_resume_stream_generator"),
        ("agno.os.routers.teams.router", "_resume_stream_generator"),
        ("agno.os.routers.workflows.router", "_resume_stream_generator"),
        ("agno.os.routers.workflows.router", "handle_workflow_subscription"),
    ],
)
def test_resume_paths_treat_unverified_as_terminal(module_path, function_name):
    # The terminal tuples live inline in the resume generators; without
    # unverified in them, a finished-but-unverified run falls through to the
    # live-tail path and the client hangs on a run that will produce nothing.
    module = __import__(module_path, fromlist=[function_name])
    source = inspect.getsource(getattr(module, function_name))
    assert "RunStatus.unverified" in source


# --- job queue: ticket vocabulary and status coercion -----------------------


def test_ticket_status_to_api_maps_unverified():
    from agno.os.job_queue import ticket_status_to_api

    assert ticket_status_to_api("unverified") == "UNVERIFIED"


def test_run_status_round_trips_unverified_string():
    # The queue executor coerces a DB-read plain-str status back through the
    # enum before publishing the terminal sentinel; the member existing is
    # what keeps UNVERIFIED from being coerced to ERROR there.
    assert RunStatus("UNVERIFIED") is RunStatus.unverified
    assert RunStatus.unverified == "UNVERIFIED"


# --- scheduler: poller terminal set -----------------------------------------


def test_scheduler_terminal_statuses_include_unverified():
    # String literals by design: the poller compares statuses read off HTTP
    # responses, so the enum member alone does not cover this file.
    from agno.scheduler.executor import _TERMINAL_STATUSES

    assert "UNVERIFIED" in _TERMINAL_STATUSES


def test_scheduler_poll_maps_unverified_to_failed():
    from agno.scheduler.executor import ScheduleExecutor

    source = inspect.getsource(ScheduleExecutor)
    assert '"UNVERIFIED"' in source


# --- os/schema.py: run projections carry verification -----------------------


def test_run_schema_from_dict_carries_verification():
    from agno.os.schema import RunSchema

    record = {"status": "unverified", "stop_reason": "exhausted", "attempts": []}
    schema = RunSchema.from_dict({"run_id": "r1", "status": "UNVERIFIED", "verification": record})
    assert schema.verification == record
    assert schema.status == "UNVERIFIED"


def test_run_schema_from_dict_verification_defaults_to_none():
    from agno.os.schema import RunSchema

    assert RunSchema.from_dict({"run_id": "r1"}).verification is None


def test_team_run_schema_from_dict_carries_verification():
    from agno.os.schema import TeamRunSchema

    record = {"status": "verified", "stop_reason": "passed", "attempts": []}
    schema = TeamRunSchema.from_dict({"run_id": "r1", "verification": record})
    assert schema.verification == record


# --- os/mcp_results.py: trimmed projections ---------------------------------


def _run_output_with_verification(verification):
    from agno.run.agent import RunOutput

    return RunOutput(
        run_id="r1",
        session_id="s1",
        content="the answer",
        status=RunStatus.unverified,
        verification=verification,
    )


def test_trimmed_structured_content_carries_verification_summary():
    pytest.importorskip("mcp")
    from agno.os.mcp_results import trimmed_structured_content

    verification = Verification(status="unverified", stop_reason="exhausted")
    structured = trimmed_structured_content(_run_output_with_verification(verification))
    assert structured["status"] == "UNVERIFIED"
    assert structured["verification"] == {"status": "unverified", "stop_reason": "exhausted"}
    # The compact summary only: attempts/verdicts stay out of the trimmed view.
    assert "attempts" not in structured["verification"]


def test_trimmed_structured_content_accepts_dict_verification():
    # After a DB round-trip the record arrives as a plain dict.
    pytest.importorskip("mcp")
    from agno.os.mcp_results import trimmed_structured_content

    run_output = _run_output_with_verification(None)
    run_output.verification = {"status": "verified", "stop_reason": "passed", "attempts": []}
    structured = trimmed_structured_content(run_output)
    assert structured["verification"] == {"status": "verified", "stop_reason": "passed"}


def test_trimmed_structured_content_omits_verification_when_absent():
    pytest.importorskip("mcp")
    from agno.os.mcp_results import trimmed_structured_content

    structured = trimmed_structured_content(_run_output_with_verification(None))
    assert "verification" not in structured


def test_session_run_history_fields_include_verification():
    pytest.importorskip("mcp")
    from agno.os.mcp_results import SESSION_RUN_HISTORY_FIELDS, trim_session_run

    assert "verification" in SESSION_RUN_HISTORY_FIELDS
    record = {"status": "unverified", "stop_reason": "exhausted"}
    trimmed = trim_session_run({"run_id": "r1", "content": "answer", "verification": record, "messages": ["kept-out"]})
    assert trimmed["verification"] == record
    assert "messages" not in trimmed
