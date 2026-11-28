"""GET /sessions/{id}/run-previews reads through the projected path, locally and over RemoteDb."""

from typing import Any, List
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.client.os import AgentOSClient
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.schema import RunSchema, SessionRunPreviewSchema
from agno.remote.base import RemoteDb
from tests.unit.db.test_session_run_previews import seed


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "route.db"))


@pytest.fixture
async def client(db):
    await seed(db)
    return TestClient(AgentOS(agents=[Agent(name="a", id="agent-1", db=db)]).get_app())


def _no_full_reads(monkeypatch) -> None:
    from agno.os.routers.session import session as session_router

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run-previews must not load full runs")

    monkeypatch.setattr(session_router, "get_session_runs_from_service", boom)


async def test_run_previews_skip_the_full_run_read(monkeypatch, client):
    _no_full_reads(monkeypatch)
    response = client.get("/sessions/s-agent/run-previews")
    assert response.status_code == 200
    assert [p["run_id"] for p in response.json()] == ["a-str", "a-structured", "a-msg-list", "a-no-input", "a-member"]


async def test_run_previews_status_filter_matches_full_listing(monkeypatch, client):
    full = client.get("/sessions/s-agent/runs", params={"status": ["running", "Paused"]})
    _no_full_reads(monkeypatch)
    previews = client.get("/sessions/s-agent/run-previews", params={"status": ["running", "Paused"]})
    assert previews.status_code == full.status_code == 200
    assert (
        [p["run_id"] for p in previews.json()] == [r["run_id"] for r in full.json()] == ["a-structured", "a-msg-list"]
    )
    assert client.get("/sessions/s-agent/run-previews", params={"status": ["FAILED"]}).status_code == 400


async def test_run_previews_keep_user_scoping(monkeypatch, client):
    _no_full_reads(monkeypatch)
    assert client.get("/sessions/s-agent/run-previews", params={"user_id": "u1"}).status_code == 200
    assert client.get("/sessions/s-agent/run-previews", params={"user_id": "intruder"}).status_code == 404
    assert client.get("/sessions/missing/run-previews").status_code == 404


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://remote/sessions/s/run-previews")
    return httpx.HTTPStatusError("err", request=request, response=httpx.Response(status, request=request))


def _remote(previews: Any = None, runs: Any = None) -> RemoteDb:
    remote = RemoteDb.__new__(RemoteDb)
    # spec keeps the mock's sync/async method pairs honest: awaiting a sync method fails here too.
    remote.client = MagicMock(spec=AgentOSClient)  # type: ignore[attr-defined]
    remote.client.aget_session_run_previews = AsyncMock(side_effect=previews)
    remote.client.get_session_runs = AsyncMock(return_value=runs or [])
    return remote


def _runs() -> List[RunSchema]:
    return [
        RunSchema(run_id="r1", agent_id="a", status="COMPLETED", run_input="hi " * 200, content="ok"),
        RunSchema(run_id="r2", agent_id="a", status="RUNNING", run_input="yo", content="..."),
    ]


async def test_remote_previews_use_the_remote_endpoint():
    preview = SessionRunPreviewSchema(run_id="r1", status="COMPLETED")
    remote = _remote(previews=[[preview]])
    assert await remote.get_session_run_previews("s", status=["COMPLETED"]) == [preview]
    remote.client.get_session_runs.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.parametrize("status_code", [404, 405])
async def test_remote_previews_fall_back_on_older_agentos(status_code):
    remote = _remote(previews=_http_error(status_code), runs=_runs())
    previews = await remote.get_session_run_previews("s", user_id="u1", status=["COMPLETED"])
    assert [p.model_dump() for p in previews] == [SessionRunPreviewSchema.from_run(r).model_dump() for r in _runs()]
    kwargs = remote.client.get_session_runs.call_args.kwargs  # type: ignore[attr-defined]
    assert kwargs["user_id"] == "u1" and kwargs["status"] == ["COMPLETED"]


async def test_remote_previews_propagate_other_errors():
    remote = _remote(previews=_http_error(500))
    with pytest.raises(httpx.HTTPStatusError):
        await remote.get_session_run_previews("s")
    remote.client.get_session_runs.assert_not_called()  # type: ignore[attr-defined]
