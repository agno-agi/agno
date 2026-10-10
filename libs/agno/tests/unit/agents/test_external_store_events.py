"""Stored events on external agent runs, mirroring Agent.store_events."""

import asyncio
from typing import Any, List

import pytest

from agno.db.sqlite import SqliteDb
from agno.run.agent import RunEvent, RunOutput
from agno.run.base import RunStatus
from tests.unit.agents.test_external_retries import FlakyAgent


def _stream(agent: FlakyAgent, **kwargs: Any) -> List[Any]:
    async def consume():
        return [event async for event in agent._arun_stream("go", yield_run_output=True, **kwargs)]

    return asyncio.run(consume())


def _kinds(run: RunOutput) -> List[str]:
    return [event.event for event in run.events or []]


def test_events_are_not_stored_by_default(tmp_path):
    agent = FlakyAgent(id="flaky", db=SqliteDb(db_file=str(tmp_path / "runs.db")), failures=0)
    run = _stream(agent, session_id="s")[-1]
    assert agent.store_events is False and run.events is None
    assert not agent.get_run_output(run.run_id, "s").events, "deserialized as an empty list, as for Agent"


def test_streamed_events_are_stored_on_the_run_without_content_deltas(tmp_path):
    agent = FlakyAgent(id="flaky", db=SqliteDb(db_file=str(tmp_path / "runs.db")), failures=0, store_events=True)
    events = _stream(agent, session_id="s")
    run = events[-1]
    assert _kinds(run) == ["RunStarted", "ToolCallStarted", "ToolCallCompleted", "RunCompleted"]
    assert "RunContent" in [e.event for e in events[:-1]], "content deltas are streamed"
    assert "RunContent" not in _kinds(run), "but not stored; the run keeps the full content instead"
    assert run.events[0] is events[0], "the stored RunStarted is the streamed one"
    stored = agent.get_run_output(run.run_id, "s")
    assert _kinds(stored) == _kinds(run), "events survive persistence"
    assert stored.events[-1].content == "partial 1 answer 1"
    assert stored.events[2].tool.result == "ok"
    assert stored.events[1].tool.result is None, "the started event is not rewritten when the tool completes"


def test_events_to_skip_can_be_changed():
    agent = FlakyAgent(id="flaky", failures=0, store_events=True, events_to_skip=[])
    run = _stream(agent)[-1]
    assert _kinds(run) == [
        "RunStarted",
        "RunContent",
        "ToolCallStarted",
        "ToolCallCompleted",
        "RunContent",
        "RunCompleted",
    ]
    agent = FlakyAgent(id="flaky", failures=0, store_events=True, events_to_skip=[RunEvent.tool_call_started])
    kinds = _kinds(_stream(agent)[-1])
    assert "ToolCallStarted" not in kinds and "RunContent" in kinds


def test_error_and_retry_events_are_stored():
    failing = FlakyAgent(id="flaky", failures=5, store_events=True)
    run = _stream(failing)[-1]
    assert run.status == RunStatus.error
    assert _kinds(run) == ["RunStarted", "ToolCallStarted", "ToolCallCompleted", "RunError"]
    assert run.events[-1].content == "attempt 1 failed"

    retried = FlakyAgent(id="flaky", retries=1, failures=1, store_events=True)
    run = _stream(retried)[-1]
    kinds = _kinds(run)
    assert kinds[0] == "RunStarted" and kinds[-1] == "RunCompleted"
    assert kinds.count("ToolCallCompleted") == 2, "both attempts' tool events are kept"
    retry_events = [e for e in run.events if e.event == "CustomEvent"]
    assert len(retry_events) == 1 and retry_events[0].warning["type"] == "retry"
    assert kinds.index("CustomEvent") == 3, "the retry warning sits between the attempts"


@pytest.mark.asyncio
async def test_cancelled_runs_store_the_cancel_event():
    agent = FlakyAgent(id="flaky", retries=3, failures=5, delay_between_retries=30, store_events=True)

    async def run() -> RunOutput:
        events = [e async for e in agent._arun_stream("go", run_id="r1", yield_run_output=True)]
        return events[-1]

    task = asyncio.create_task(run())
    while not agent.attempts:
        await asyncio.sleep(0.01)
    await agent.acancel_run("r1")
    out = await asyncio.wait_for(task, 3)
    assert out.status == RunStatus.cancelled and _kinds(out)[-1] == "RunCancelled"


def test_non_streaming_runs_store_no_events(tmp_path):
    agent = FlakyAgent(id="flaky", db=SqliteDb(db_file=str(tmp_path / "runs.db")), failures=0, store_events=True)
    run = agent.run("go", session_id="s")
    assert run.status == RunStatus.completed and run.events is None


def test_agentos_turns_event_storage_on(tmp_path):
    from agno.os import AgentOS

    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = FlakyAgent(id="flaky", failures=0)
    AgentOS(agents=[agent], db=db).get_app()
    assert agent.store_events is True and agent.db is db


def _sse_payloads(text: str) -> List[dict]:
    import json

    return [json.loads(line.split("data: ", 1)[1]) for line in text.split("\n") if line.startswith("data: ")]


def test_agentos_resume_replays_a_finished_run_from_the_database(tmp_path):
    """PATH 3 of /resume: the run is not in the live event stream, so the stored events are replayed."""
    from fastapi.testclient import TestClient

    from agno.os import AgentOS

    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = FlakyAgent(id="flaky", failures=0)
    app = AgentOS(agents=[agent], db=db).get_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/agents/flaky/runs", data={"message": "go", "stream": "true", "session_id": "s"})
    assert resp.status_code == 200
    live = _sse_payloads(resp.text)
    run_id = live[0]["run_id"]
    assert [p["event"] for p in live] == [
        "RunStarted",
        "RunContent",
        "ToolCallStarted",
        "ToolCallCompleted",
        "RunContent",
        "RunCompleted",
    ]
    stored = agent.get_run_output(run_id, "s")
    assert _kinds(stored) == ["RunStarted", "ToolCallStarted", "ToolCallCompleted", "RunCompleted"]

    resp = client.post(f"/agents/flaky/runs/{run_id}/resume", data={"session_id": "s"})
    assert resp.status_code == 200
    replay = _sse_payloads(resp.text)
    assert replay[0]["event"] == "replay" and replay[0]["total_events"] == 4
    assert [p["event"] for p in replay[1:]] == ["RunStarted", "ToolCallStarted", "ToolCallCompleted", "RunCompleted"]
    assert [p["event_index"] for p in replay[1:]] == [0, 1, 2, 3], "the inline stream does not stamp indices"
    assert replay[-1]["content"] == "partial 1 answer 1"
    assert replay[3]["tool"]["result"] == "ok"


@pytest.mark.asyncio
async def test_background_runs_store_stream_indices_for_replay_floors(tmp_path):
    """Queued runs publish through the event stream, which stamps each stored event with its real index, so
    a client's last_event_index applies to the replay once the buffer has forgotten the run."""
    from fastapi.testclient import TestClient

    from agno.os import AgentOS
    from agno.os.event_streams import get_event_stream

    from ._queue_harness import run_through_queue

    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = FlakyAgent(id="flaky", failures=0)
    app = AgentOS(agents=[agent], db=db).get_app()
    job = await run_through_queue(agent, stream=True, max_attempts=1)
    assert job["status"] == "completed"

    stored = await agent.aget_run_output(job["id"], "s")
    assert _kinds(stored) == ["RunStarted", "ToolCallStarted", "ToolCallCompleted", "RunCompleted"]
    indices = [e.event_index for e in stored.events]
    assert indices[:3] == [0, 2, 3], "RunContent took index 1 on the stream but is not stored"
    assert indices[3] is None, "the terminal event is persisted before it is published, as for Agent"

    await get_event_stream().cleanup_run(job["id"])
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(f"/agents/flaky/runs/{job['id']}/resume", data={"session_id": "s", "last_event_index": "2"})
    assert resp.status_code == 200
    tail = _sse_payloads(resp.text)
    assert [(p["event"], p["event_index"]) for p in tail[1:]] == [("ToolCallCompleted", 3), ("RunCompleted", 3)]
