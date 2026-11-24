"""What a worker does with the run an earlier claim started for the same event."""

import httpx
import pytest

from agno.db.schemas.scheduler import Schedule
from agno.triggers.executor import TriggerExecutor

ROW = {"id": "te-1", "run_id": "run-1", "session_id": "session-1"}
CALL = Schedule(id="trg-1", name="triage", cron_expr="", endpoint="/agents/engineer/runs")


def executor_seeing(run: dict, status_code: int = 200):
    requests = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={})
        return httpx.Response(status_code, json=run)

    executor = TriggerExecutor(base_url="http://agentos.test", internal_service_token="internal-token")
    executor._client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    return executor, requests


async def test_a_completed_run_is_the_events_result():
    executor, requests = executor_seeing({"status": "COMPLETED", "content": "done", "content_type": "str"})

    result = await executor._recorded_run(CALL, ROW)

    assert result is not None
    assert result["status"] == "success" and result["run_id"] == "run-1"
    assert result["output"] == {"content": "done", "content_type": "str"}
    (request,) = requests
    assert str(request.url) == "http://agentos.test/agents/engineer/runs/run-1?session_id=session-1"
    assert request.headers["authorization"] == "Bearer internal-token"


async def test_a_run_waiting_on_a_person_is_the_events_result():
    requirement = {"id": "req-1"}
    executor, requests = executor_seeing({"status": "PAUSED", "requirements": [requirement]})

    result = await executor._recorded_run(CALL, ROW)

    assert result is not None
    assert result["status"] == "paused" and result["requirements"] == [requirement]
    assert len(requests) == 1


@pytest.mark.parametrize("status", ["CANCELLED", "ERROR"])
async def test_a_run_that_stopped_with_its_worker_is_run_again(status):
    executor, requests = executor_seeing({"status": status})

    assert await executor._recorded_run(CALL, ROW) is None
    # Nothing is left to stop.
    assert [request.method for request in requests] == ["GET"]


async def test_a_run_nobody_follows_is_asked_to_stop_and_run_again():
    executor, requests = executor_seeing({"status": "RUNNING"})

    assert await executor._recorded_run(CALL, ROW) is None
    assert [request.method for request in requests] == ["GET", "POST"]
    assert str(requests[1].url) == "http://agentos.test/agents/engineer/runs/run-1/cancel"


async def test_a_run_that_cannot_be_found_is_run_again():
    executor, requests = executor_seeing({"detail": "Run not found"}, status_code=404)

    assert await executor._recorded_run(CALL, ROW) is None
    assert [request.method for request in requests] == ["GET"]
