"""Session-busy conflicts preserve keep-alive; other Agno errors retain their existing handling."""

import http.client
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agno.agents.base import BaseExternalAgent
from agno.db.sqlite import SqliteDb
from agno.exceptions import AgnoError, ModelProviderError, SessionBusyError
from agno.os import AgentOS
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


@dataclass
class QuietAgent(BaseExternalAgent):
    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        return "ok"


def _busy_app(tmp_path, base_app=None):
    """An AgentOS whose only session has a turn in flight, so every run is a 409."""
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = QuietAgent(id="quiet", db=db)
    db.upsert_session(AgentSession(session_id="s", agent_id="quiet"))
    db.upsert_run(
        run=RunOutput(run_id="busy", session_id="s", agent_id="quiet", status=RunStatus.running), session_id="s"
    )
    return AgentOS(agents=[agent], db=db, telemetry=False, base_app=base_app).get_app()


@pytest.mark.parametrize("use_base_app", [False, True])
def test_session_busy_is_handled_not_reraised(tmp_path, use_base_app):
    # raise_server_exceptions=True: an exception that escapes the app's handlers surfaces here.
    client = TestClient(_busy_app(tmp_path, FastAPI() if use_base_app else None))
    resp = client.post("/agents/quiet/runs", data={"message": "hi", "session_id": "s", "stream": "false"})
    assert resp.status_code == 409
    assert resp.json()["error_id"] == "session_busy" and resp.json()["error_type"] == "session_busy"
    assert "busy" in resp.json()["detail"]
    client.close()


@pytest.mark.parametrize(
    "error", [AgnoError("other conflict", status_code=409), ModelProviderError("provider failure")]
)
@pytest.mark.parametrize("use_base_app", [False, True])
def test_other_agno_errors_keep_existing_handling(tmp_path, error, use_base_app):
    app = _busy_app(tmp_path, FastAPI() if use_base_app else None)

    @app.get("/test-error")
    async def raise_error():
        raise error

    client = TestClient(app)
    try:
        with pytest.raises(type(error)) as caught:
            client.get("/test-error")
        assert caught.value is error
    finally:
        client.close()

    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/test-error")
        if use_base_app:
            # The default FastAPI server-error response is unchanged.
            assert response.status_code == 500
            assert response.text == "Internal Server Error"
            return
        assert response.status_code == error.status_code
        assert response.json() == {
            "detail": str(error) if error.status_code < 500 else f"Internal server error ({type(error).__name__})",
            "error_id": error.error_id,
            "error_type": error.type,
        }
    finally:
        client.close()


@pytest.mark.parametrize("use_base_app", [False, True])
def test_session_busy_409_keeps_the_connection_open(tmp_path, use_base_app):
    app = _busy_app(tmp_path, FastAPI() if use_base_app else None)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        assert server.started
        conn.connect()
        original_socket = conn.sock
        body = urllib.parse.urlencode({"message": "hi", "session_id": "s", "stream": "false"})
        statuses = []
        for _ in range(3):
            # The same connection every time: a server that closed it after the 409 would make
            # the next request fail with RemoteDisconnected.
            conn.request(
                "POST", "/agents/quiet/runs", body=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response = conn.getresponse()
            response.read()
            assert conn.sock is original_socket
            statuses.append((response.status, response.will_close))
        assert statuses == [(409, False)] * 3
    finally:
        conn.close()
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.parametrize("error_type", [SessionBusyError, AgnoError])
def test_base_app_preserves_typed_conflict_handler(tmp_path, error_type):
    base_app = FastAPI()

    @base_app.exception_handler(error_type)
    async def custom_handler(request, exc):
        return JSONResponse(status_code=409, content={"custom": exc.error_id}, headers={"X-Custom": "preserved"})

    app = _busy_app(tmp_path, base_app)
    assert app.exception_handlers[error_type] is custom_handler
    if error_type is AgnoError:
        assert SessionBusyError not in app.exception_handlers
    client = TestClient(app)
    try:
        response = client.post("/agents/quiet/runs", data={"message": "hi", "session_id": "s", "stream": "false"})
        assert response.status_code == 409
        assert response.json() == {"custom": "session_busy"}
        assert response.headers["X-Custom"] == "preserved"
    finally:
        client.close()


def test_base_app_catch_all_still_handles_unexpected_errors(tmp_path):
    base_app = FastAPI()

    @base_app.exception_handler(Exception)
    async def custom_handler(request, exc):
        return JSONResponse(status_code=500, content={"custom": "server error"})

    @base_app.get("/test-error")
    async def raise_error():
        raise RuntimeError("unexpected")

    app = _busy_app(tmp_path, base_app)
    assert app.exception_handlers[Exception] is custom_handler
    client = TestClient(app)
    try:
        response = client.post("/agents/quiet/runs", data={"message": "hi", "session_id": "s", "stream": "false"})
        assert response.status_code == 409
        assert response.json()["error_id"] == "session_busy"
        with pytest.raises(RuntimeError, match="unexpected"):
            client.get("/test-error")
    finally:
        client.close()
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/test-error")
        assert response.status_code == 500
        assert response.json() == {"custom": "server error"}
    finally:
        client.close()
