"""Unit tests for BrowserUseTools against a fake Browser Use API v4."""

import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx
import pytest

pytest.importorskip("browser_use_sdk")

from agno.tools.browser_use import BrowserUseTools  # noqa: E402

RUN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "22222222-2222-2222-2222-222222222222"
WORKSPACE_ID = "33333333-3333-3333-3333-333333333333"


def _summary(status: str, result: Optional[str] = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": RUN_ID,
        "task": "t",
        "title": None,
        "model": "m",
        "contextLimit": 1,
        "status": status,
        "result": result,
        "error": error,
        "sessionId": SESSION_ID,
        "workspaceId": WORKSPACE_ID,
        "totalInputTokens": 0,
        "totalOutputTokens": 0,
        "totalCostUsd": "0",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }


class FakeBrowserUseApi:
    """Records requests and answers like the v4 runs endpoints."""

    def __init__(self) -> None:
        self.final_status = "completed"
        self.result: Optional[str] = "42"
        self.error: Optional[str] = None
        self.create_status_code = 200
        self.requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/api/v4/runs":
            if self.create_status_code != 200:
                return httpx.Response(self.create_status_code, json={"detail": "slow down"})
            return httpx.Response(
                200,
                json={
                    "id": RUN_ID,
                    "status": "queued",
                    "model": "m",
                    "sessionId": SESSION_ID,
                    "workspaceId": WORKSPACE_ID,
                    "eventsUrl": "/events",
                },
            )
        if path == f"/api/v4/runs/{RUN_ID}/status":
            return httpx.Response(200, json={"status": self.final_status})
        if path == f"/api/v4/runs/{RUN_ID}/cancel":
            return httpx.Response(200, json=_summary("cancelled"))
        if path == f"/api/v4/runs/{RUN_ID}":
            return httpx.Response(200, json=_summary(self.final_status, self.result, self.error))
        return httpx.Response(404, json={"detail": "not found"})

    def created_body(self) -> Dict[str, Any]:
        create = next(r for r in self.requests if r.method == "POST")
        return json.loads(create.content)

    def paths(self) -> List[str]:
        return [r.url.path for r in self.requests]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeBrowserUseApi:
    fake = FakeBrowserUseApi()
    transport = httpx.MockTransport(fake)
    real_client, real_async_client = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: real_client(*a, transport=transport, **kw))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_async_client(*a, transport=transport, **kw))
    monkeypatch.setenv("BROWSER_USE_API_KEY", "test-key")
    return fake


def test_registers_sync_and_async_tool(api: FakeBrowserUseApi) -> None:
    tools = BrowserUseTools()

    assert [t.__name__ for t in tools.tools] == ["run_browser_task"]
    assert tools.timeout == 900


def test_runs_task_and_returns_result_with_session(api: FakeBrowserUseApi) -> None:
    result = BrowserUseTools(model="claude-sonnet-5").run_browser_task("Find the answer")

    assert json.loads(result) == {"result": "42", "session_id": SESSION_ID, "run_id": RUN_ID}
    assert api.created_body() == {"task": "Find the answer", "model": "claude-sonnet-5"}
    assert api.requests[0].headers["X-Browser-Use-API-Key"] == "test-key"


def test_follow_up_continues_the_session(api: FakeBrowserUseApi) -> None:
    BrowserUseTools().run_browser_task("Now open the second result", session_id=SESSION_ID)

    assert api.created_body() == {"task": "Now open the second result", "sessionId": SESSION_ID}


def test_failed_run_returns_error(api: FakeBrowserUseApi) -> None:
    api.final_status, api.result, api.error = "failed", None, "site blocked"

    result = json.loads(BrowserUseTools().run_browser_task("t"))

    assert "site blocked" in result["error"]
    assert result["session_id"] == SESSION_ID


def test_timeout_cancels_the_run(api: FakeBrowserUseApi) -> None:
    api.final_status = "running"

    result = json.loads(BrowserUseTools(timeout=0).run_browser_task("t"))

    assert "cancelled" in result["error"]
    assert f"/api/v4/runs/{RUN_ID}/cancel" in api.paths()


def test_api_error_is_returned(api: FakeBrowserUseApi) -> None:
    api.create_status_code = 429

    result = json.loads(BrowserUseTools().run_browser_task("t"))

    assert "429" in result["error"]


def test_missing_api_key_makes_no_request(api: FakeBrowserUseApi, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROWSER_USE_API_KEY")

    result = json.loads(BrowserUseTools().run_browser_task("t"))

    assert "BROWSER_USE_API_KEY" in result["error"]
    assert api.requests == []


def test_async_run_returns_result(api: FakeBrowserUseApi) -> None:
    result = asyncio.run(BrowserUseTools().arun_browser_task("Find the answer"))

    assert json.loads(result)["result"] == "42"
    assert api.created_body() == {"task": "Find the answer"}


def test_async_timeout_cancels_the_run(api: FakeBrowserUseApi) -> None:
    api.final_status = "running"

    result = json.loads(asyncio.run(BrowserUseTools(timeout=0).arun_browser_task("t")))

    assert "cancelled" in result["error"]
    assert f"/api/v4/runs/{RUN_ID}/cancel" in api.paths()
