"""How the executor follows a run it started, and what it does with the run an earlier claim started."""

import time
from typing import Any, List, Tuple

import httpx
import pytest

from agno.run.authorization import AUTHORIZATION_HEADER
from agno.triggers.executor import ClaimLost, Deferred, TriggerExecutor, _on_accepted

ENDPOINT = "/agents/engineer/runs"
ROW = {"id": "te-1", "run_id": "run-1", "session_id": "session-1"}
RUN_URL = "http://agentos.test/agents/engineer/runs/run-1"

COMPLETED = (200, {"status": "COMPLETED", "content": "done", "content_type": "str"})
RUNNING = (200, {"status": "RUNNING"})
CANCELLED = (200, {"status": "CANCELLED"})
UNAVAILABLE = (503, {"detail": "unavailable"})


def executor_seeing(*reads: Any, cancel_status: int = 200) -> Tuple[TriggerExecutor, List[httpx.Request]]:
    """An executor whose reads of the run are answered in order; the last answer repeats.

    A read given as an exception is raised, as a broken connection would be.
    """
    answers = list(reads)
    requests: List[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(cancel_status, json={})
        read = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(read, Exception):
            raise read
        return httpx.Response(read[0], json=read[1])

    executor = TriggerExecutor(
        base_url="http://agentos.test",
        internal_service_token="internal-token",
        poll_interval=0,
        read_backoff=0,
        stop_grace_seconds=0.05,
    )
    executor._client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    return executor, requests


def methods(requests: List[httpx.Request]) -> List[str]:
    return [request.method for request in requests]


# ------------------------------------------------------------- the run an earlier claim started


async def test_a_completed_run_is_the_events_result():
    executor, requests = executor_seeing(COMPLETED)

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    assert result is not None
    assert result["status"] == "success" and result["run_id"] == "run-1"
    assert result["output"] == {"content": "done", "content_type": "str"}
    (request,) = requests
    assert str(request.url) == f"{RUN_URL}?session_id=session-1"
    assert request.headers["authorization"] == "Bearer internal-token"


async def test_a_run_waiting_on_a_person_is_the_events_result():
    requirement = {"id": "req-1"}
    executor, requests = executor_seeing((200, {"status": "PAUSED", "requirements": [requirement]}))

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    assert result is not None
    assert result["status"] == "paused" and result["requirements"] == [requirement]
    assert methods(requests) == ["GET"]


async def test_a_run_cancelled_with_its_worker_may_be_run_again():
    executor, requests = executor_seeing(CANCELLED)

    # A process that shuts down cancels the runs it has in flight. The event is run again.
    assert await executor._recorded_run(ENDPOINT, ROW, 3600) is None
    # Nothing is left to stop.
    assert methods(requests) == ["GET"]


async def test_a_run_that_had_already_failed_is_the_attempts_result():
    executor, requests = executor_seeing((200, {"status": "ERROR", "error": "the model is down"}))

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    # It counts as the attempt it was, so the trigger's retries decide whether another is made.
    assert result is not None and result["status"] == "failed" and result["error"] == "the model is down"
    assert result.get("resubmit") is not False
    assert methods(requests) == ["GET"]


async def test_a_failed_read_is_tried_again():
    executor, requests = executor_seeing(UNAVAILABLE, COMPLETED)

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    assert result is not None and result["status"] == "success"
    assert methods(requests) == ["GET", "GET"]


async def test_a_broken_connection_is_tried_again():
    executor, requests = executor_seeing(httpx.ConnectError("connection refused"), COMPLETED)

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    assert result is not None and result["status"] == "success"


async def test_a_run_that_cannot_be_read_is_left_for_a_later_attempt():
    executor, requests = executor_seeing(UNAVAILABLE)

    with pytest.raises(Deferred):
        await executor._recorded_run(ENDPOINT, ROW, 3600)
    # Read as many times as the executor is told to, and never asked to stop: nothing is known about it.
    assert methods(requests) == ["GET"] * executor.read_attempts


async def test_a_run_still_going_is_followed_to_its_end():
    executor, requests = executor_seeing(RUNNING, RUNNING, COMPLETED)

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    # It is read until it ends, and never asked to stop: its result is the event's result.
    assert result is not None and result["status"] == "success"
    assert result["output"] == {"content": "done", "content_type": "str"}
    assert methods(requests) == ["GET", "GET", "GET"]


@pytest.mark.parametrize("ended, status", [("CANCELLED", "cancelled"), ("ERROR", "failed")])
async def test_a_followed_run_that_ends_badly_is_the_events_result(ended, status):
    executor, requests = executor_seeing(RUNNING, (200, {"status": ended}))

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    # This worker saw it end, so it is the attempt's own result: a failed one may be retried as
    # the trigger allows, a cancelled one is not.
    assert result is not None and result["status"] == status
    assert result.get("resubmit") is not False
    assert methods(requests) == ["GET", "GET"]


async def test_a_run_still_going_is_asked_to_stop_only_when_its_timeout_has_passed():
    started = int(time.time()) - 7200
    executor, requests = executor_seeing(
        (200, {"status": "RUNNING", "created_at": started}), (200, {"status": "RUNNING"}), CANCELLED
    )

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    # Its timeout passed before this worker found it. Seen to stop, it has failed and may be retried.
    assert result is not None and result["status"] == "failed"
    assert result["error"] == "Run run-1 was stopped after its timeout of 3600s"
    assert result.get("resubmit") is not False
    assert methods(requests)[:3] == ["GET", "GET", "POST"]
    assert str(requests[2].url) == f"{RUN_URL}/cancel?session_id=session-1"
    assert requests[2].headers["authorization"] == "Bearer internal-token"


async def test_a_refused_cancel_is_not_taken_for_a_stopped_run():
    started = int(time.time()) - 7200
    executor, requests = executor_seeing((200, {"status": "RUNNING", "created_at": started}), cancel_status=500)

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    assert result is not None and result["status"] == "failed" and result["resubmit"] is False


async def test_a_run_past_its_timeout_that_does_not_stop_fails_the_event_without_a_second_run():
    started = int(time.time()) - 7200
    executor, requests = executor_seeing((200, {"status": "RUNNING", "created_at": started}))

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    assert result is not None
    assert result["status"] == "failed" and result["resubmit"] is False
    assert "did not stop after its timeout of 3600s" in result["error"]
    assert "not run again" in result["error"]


async def test_a_run_that_does_not_exist_fails_the_event_without_a_second_run():
    executor, requests = executor_seeing((404, {"detail": "Run not found"}))

    result = await executor._recorded_run(ENDPOINT, ROW, 3600)

    assert result is not None
    assert result["status"] == "failed" and result["resubmit"] is False
    assert "was not found" in result["error"] and "not run again" in result["error"]
    assert methods(requests) == ["GET"] * executor.read_attempts


# --------------------------------------------------------------------- following an accepted run


async def test_a_run_is_followed_with_the_executors_own_token():
    executor, requests = executor_seeing(RUNNING, COMPLETED)
    # What the run was started with: the creator's saved authority.
    started_with = {"Authorization": "Bearer internal-token", AUTHORIZATION_HEADER: '{"context": {}}'}

    result = await executor._poll_run(None, started_with, "agents", "engineer", "run-1", "session-1", 3600)

    assert result["status"] == "success"
    assert methods(requests) == ["GET", "GET"]
    for request in requests:
        assert request.headers["authorization"] == "Bearer internal-token"
        assert AUTHORIZATION_HEADER.lower() not in request.headers


async def test_a_refused_read_does_not_end_the_run():
    executor, requests = executor_seeing((403, {"detail": "Insufficient permissions"}), UNAVAILABLE, COMPLETED)

    result = await executor._follow_run("agents", "engineer", "run-1", "session-1", 3600)

    assert result["status"] == "success"
    assert methods(requests) == ["GET", "GET", "GET"]


async def test_a_run_stopped_after_its_timeout_has_failed_and_may_be_retried():
    executor, requests = executor_seeing(RUNNING, RUNNING, CANCELLED)

    result = await executor._follow_run("agents", "engineer", "run-1", "session-1", 0)

    assert result["status"] == "failed"
    assert result["error"] == "Run run-1 was stopped after its timeout of 0s"
    assert result.get("resubmit") is not False
    assert "POST" in methods(requests)


async def test_a_run_that_does_not_stop_after_its_timeout_is_not_run_again():
    executor, requests = executor_seeing(RUNNING)

    result = await executor._follow_run("agents", "engineer", "run-1", "session-1", 0)

    assert result["status"] == "failed" and result["resubmit"] is False
    assert result["error"] == "Run run-1 did not stop after its timeout of 0s; the event was not run again"
    assert "POST" in methods(requests)


async def test_a_run_accepted_after_the_claim_was_lost_is_asked_to_stop():
    executor, requests = executor_seeing(RUNNING)

    async def lost(run_id: str, session_id: str) -> bool:
        return False

    token = _on_accepted.set(lost)
    try:
        with pytest.raises(ClaimLost):
            await executor._poll_run(None, {}, "agents", "engineer", "run-1", "session-1", 0)
    finally:
        _on_accepted.reset(token)
    # It is not followed: the worker that holds the event starts its own.
    assert methods(requests) == ["POST"]
    assert str(requests[0].url) == f"{RUN_URL}/cancel?session_id=session-1"
