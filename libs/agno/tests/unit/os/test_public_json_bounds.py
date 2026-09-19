"""Non-streaming output admission through native AgentOS routes and real HTTP."""

import socket
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.postgres import PostgresDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.public import FileUploadLimits, PublicSurface
from agno.os.public._limits import Admission

ATTACHMENT = (b"Documentation example.\n" * 40_000)[:880_000]
ORIGIN = "https://docs.example.com"
ROUTE = "/agents/docs-agent/runs"


class ShortAnswerModel(Model):
    def __init__(self):
        super().__init__(id="short-answer", name="short-answer", provider="test")

    def invoke(self, *args, **kwargs):
        return ModelResponse(role="assistant", content="Short answer.", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class LocalAdmission:
    ready = True

    async def _aprepare(self):
        pass

    async def aconsume(self, *args, **kwargs):
        return Admission(True)


def application(*, bounded=True, model=None, team_mode=False, gzip_inner=False, expose_agent=False):
    agent = Agent(id="docs-agent", model=model or ShortAnswerModel(), db=InMemoryDb(), telemetry=False)
    from fastapi import FastAPI
    from starlette.middleware.gzip import GZipMiddleware

    from agno.team import Team

    team = Team(id="support", members=[agent], model=model or ShortAnswerModel(), db=InMemoryDb(), telemetry=False)
    surface = PublicSurface(
        agents=[agent] if not team_mode or expose_agent else [],
        teams=[team] if team_mode else [],
        max_active_runs=1,
        uploads=FileUploadLimits(max_files=12, allowed_types=((".txt", "text/plain"),)),
    )
    surface._limiter = LocalAdmission()  # type: ignore[assignment]
    base_app = FastAPI()
    if gzip_inner:
        base_app.add_middleware(GZipMiddleware, minimum_size=500)
    server = AgentOS(
        id="json-output-bounds",
        base_app=base_app,
        agents=[agent],
        teams=[team] if team_mode else [],
        db=PostgresDb(db_url="postgresql+psycopg://test:test@127.0.0.1:9/unused"),
        public=surface if bounded else None,
        auto_provision_dbs=False,
        telemetry=False,
        cors_allowed_origins=[ORIGIN],
    )
    return server.get_app(), surface


def post_attachment(client):
    return client.post(
        ROUTE,
        data={"message": "Summarize this file.", "stream": "false"},
        files={"files": ("notes.txt", ATTACHMENT, "text/plain")},
        headers={"Origin": ORIGIN},
    )


def assert_complete_output_error(response):
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"
    if "content-length" in response.headers and "content-encoding" not in response.headers:
        assert int(response.headers["content-length"]) == len(response.content)
    else:
        assert response.headers.get("transfer-encoding") == "chunked" or "content-encoding" in response.headers
    assert response.headers["access-control-allow-origin"] == ORIGIN
    error = response.json()["error"]
    assert error["code"] == "output_limit" and error["message"] == "output limit"
    assert len(error["correlation_id"]) == 32
    assert b"Documentation example" not in response.content and b"Short answer" not in response.content


def test_allowed_attachment_can_exceed_default_output_limit_with_a_short_answer():
    app, surface = application(bounded=False)
    assert len(ATTACHMENT) == 880_000 < surface.uploads.max_file_bytes < surface.max_body_bytes
    assert surface.max_output_bytes == 1024 * 1024
    with TestClient(app) as client:
        response = post_attachment(client)
    assert response.status_code == 200
    assert response.json()["content"] == "Short answer."
    assert len(response.content) > surface.max_output_bytes
    assert int(response.headers["content-length"]) == len(response.content)


def test_native_run_returns_complete_error_and_releases_capacity_on_output_overflow():
    app, surface = application()
    assert surface.max_output_bytes == 1024 * 1024
    with TestClient(app) as client:
        assert_complete_output_error(post_attachment(client))
        # The sole run slot must be available after the rejected response.
        response = client.post(ROUTE, data={"message": "Hello", "stream": "false"})
        assert response.status_code == 200 and response.json()["content"] == "Short answer."
        assert int(response.headers["content-length"]) == len(response.content)


@contextmanager
def live_server(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, http="h11", loop="asyncio", log_level="error")
        )
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            assert not worker.is_alive()


def test_default_output_limit_returns_complete_json_over_uvicorn_http():
    app, _ = application()
    with live_server(app) as url, httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
        assert_complete_output_error(post_attachment(client))
        response = client.post(ROUTE, data={"message": "Hello again", "stream": "false"})
        assert response.status_code == 200 and response.json()["content"] == "Short answer."
        assert int(response.headers["content-length"]) == len(response.content)


class FailingModel(ShortAnswerModel):
    def invoke(self, *args, **kwargs):
        raise RuntimeError("private-diagnostic-marker")


@pytest.mark.parametrize("stream", ["true", "false"])
def test_native_failed_public_run_never_exposes_model_diagnostics(stream):
    app, _ = application(model=FailingModel())
    with TestClient(app) as client:
        response = client.post(ROUTE, data={"message": "Hello", "stream": stream}, headers={"Origin": ORIGIN})
    assert "private-diagnostic-marker" not in response.text
    assert response.headers["access-control-allow-origin"] == ORIGIN
    if stream == "true":
        assert response.status_code == 200 and "event: RunError" in response.text
        assert '"error_code": "run_failed"' in response.text
    else:
        assert response.status_code == 503
        assert int(response.headers["content-length"]) == len(response.content)
        payload = response.json()
        assert set(payload) == {"error"}
        assert payload["error"]["code"] == "run_failed"
        assert len(payload["error"]["correlation_id"]) == 32


def test_native_nonpublic_failed_run_retains_diagnostics():
    app, _ = application(bounded=False, model=FailingModel())
    with TestClient(app) as client:
        response = client.post(ROUTE, data={"message": "Hello", "stream": "false"})
    assert response.status_code == 200 and response.json()["status"] == "ERROR"
    assert "private-diagnostic-marker" in response.text


@pytest.mark.parametrize("team_mode", [False, True])
@pytest.mark.parametrize("gzip_position", ["inner", "outer"])
@pytest.mark.parametrize("encoding", ["identity", "gzip"])
def test_compressed_native_runs_over_http(team_mode, gzip_position, encoding):
    from starlette.middleware.gzip import GZipMiddleware

    app, surface = application(team_mode=team_mode, gzip_inner=gzip_position == "inner")
    if gzip_position == "outer":
        app = GZipMiddleware(app, minimum_size=500)
    route = "/teams/support/runs" if team_mode else ROUTE
    with (
        live_server(app) as url,
        httpx.Client(base_url=url, timeout=10, trust_env=False, headers={"Accept-Encoding": encoding}) as client,
    ):
        response = client.post(route, data={"message": "Hello", "stream": "false"})
        assert response.status_code == 200, response.text
        assert response.json()["content"] == "Short answer."
        surface.max_output_bytes = 100
        response = client.post(route, data={"message": "Hello", "stream": "false"}, headers={"Origin": ORIGIN})
        assert_complete_output_error(response)
        surface.max_output_bytes = 1024 * 1024
        assert client.post(route, data={"message": "Again", "stream": "false"}).status_code == 200


@pytest.mark.parametrize("stream", ["true", "false"])
@pytest.mark.parametrize("team_mode", [False, True])
def test_compressed_failure_is_sanitized(team_mode, stream):
    app, _ = application(team_mode=team_mode, model=FailingModel(), gzip_inner=True)
    route = "/teams/support/runs" if team_mode else ROUTE
    with TestClient(app) as client:
        response = client.post(route, data={"message": "Hello", "stream": stream}, headers={"Accept-Encoding": "gzip"})
    assert "private-diagnostic-marker" not in response.text
    if stream == "false":
        assert response.status_code == 503 and response.json()["error"]["code"] == "run_failed"
    else:
        assert response.status_code == 200
        assert "event: " + ("TeamRunError" if team_mode else "RunError") in response.text


def test_selected_team_has_reduced_roster_and_private_members():
    app, _ = application(team_mode=True)
    with TestClient(app) as client:
        assert client.get("/agents").json() == []
        roster = client.get("/teams").json()
        assert len(roster) == 1 and set(roster[0]) == {"id", "name", "description"}
        for route in (
            "/agents/docs-agent/runs",
            "/teams/docs-agent/runs",
            "/agents/support/runs",
            "/teams/hidden/runs",
        ):
            assert client.post(route, data={"message": "hi"}).status_code == 404
        assert client.get("/teams/support").status_code == 404
        assert client.post("/teams/support/runs/not-a-uuid/cancel").status_code == 400
        assert client.post("/teams/support/runs", data={"message": "hi", "user_id": "spoof"}).status_code == 400


def test_recovered_public_team_preserves_native_member_results():
    import json

    class Delegate(ShortAnswerModel):
        def invoke(self, *args, **kwargs):
            messages = kwargs.get("messages", args[0] if args else [])
            if not any(message.role == "tool" for message in messages):
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": "delegate",
                            "type": "function",
                            "function": {
                                "name": "delegate_task_to_member",
                                "arguments": json.dumps({"member_id": "docs-agent", "task": "please answer"}),
                            },
                        }
                    ],
                    response_usage=MessageMetrics(),
                )
            return super().invoke(*args, **kwargs)

    app, surface = application(team_mode=True, model=Delegate())
    surface.teams[0].members[0].model = FailingModel()
    with TestClient(app) as client:
        response = client.post("/teams/support/runs", data={"message": "Hello", "stream": "false"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED" and payload["content"] == "Short answer."
    assert any("private-diagnostic-marker" in str(message) for message in payload["messages"])
    assert any("private-diagnostic-marker" in str(tool) for tool in payload["tools"])


def test_selected_team_and_agent_share_active_run_capacity():
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    entered, release = threading.Event(), threading.Event()

    class BlockingModel(ShortAnswerModel):
        async def ainvoke(self, *args, **kwargs):
            entered.set()
            assert await asyncio.to_thread(release.wait, 5)
            return self.invoke(*args, **kwargs)

    app, _ = application(team_mode=True, expose_agent=True, model=BlockingModel())
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, "/teams/support/runs", data={"message": "Hello", "stream": "false"})
        try:
            assert entered.wait(5)
            response = client.post(ROUTE, data={"message": "Hello", "stream": "false"})
            assert response.status_code == 503 and response.json()["error"]["code"] == "run_capacity"
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 200
        assert client.post(ROUTE, data={"message": "Again", "stream": "false"}).status_code == 200


@pytest.mark.parametrize("team_mode", [False, True])
@pytest.mark.parametrize("gzip_position", ["inner", "outer"])
@pytest.mark.parametrize("compress_sse", [False, True])
def test_encoded_sse_cannot_bypass_public_error_inspection(team_mode, gzip_position, compress_sse):
    from starlette.middleware.gzip import GZipMiddleware

    app, surface = application(team_mode=team_mode, model=FailingModel(), gzip_inner=gzip_position == "inner")
    options = {"exclude_content_types": ()} if compress_sse else {}
    if gzip_position == "inner" and compress_sse:
        for middleware in app.user_middleware:
            if middleware.cls is GZipMiddleware:
                middleware.kwargs.update(options)
    if gzip_position == "outer":
        app = GZipMiddleware(app, minimum_size=500, **options)
    route = "/teams/support/runs" if team_mode else ROUTE
    with live_server(app) as url, httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
        response = client.post(
            route, data={"message": "hi", "stream": "true"}, headers={"Accept-Encoding": "gzip", "Origin": ORIGIN}
        )
        assert "private-diagnostic-marker" not in response.text
        assert response.headers["access-control-allow-origin"] == ORIGIN
        if compress_sse and gzip_position == "inner":
            assert response.status_code == 503
            assert response.headers["content-type"] == "application/json"
            assert "content-encoding" not in response.headers
            assert int(response.headers["content-length"]) == len(response.content)
            assert response.json()["error"]["code"] == "unsupported_response_encoding"
        else:
            assert response.status_code == 200
            assert "event: " + ("TeamRunError" if team_mode else "RunError") in response.text
            assert '"error_code": "run_failed"' in response.text
        component = surface.teams[0] if team_mode else surface.agents[0]
        component.model = ShortAnswerModel()
        following = client.post(
            route, data={"message": "again", "stream": "false"}, headers={"Accept-Encoding": "identity"}
        )
        assert following.status_code == 200 and following.json()["content"] == "Short answer."
