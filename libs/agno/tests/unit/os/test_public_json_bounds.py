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


def application(*, bounded=True, model=None):
    agent = Agent(id="docs-agent", model=model or ShortAnswerModel(), db=InMemoryDb(), telemetry=False)
    surface = PublicSurface(
        agents=[agent],
        max_active_runs=1,
        uploads=FileUploadLimits(max_files=12, allowed_types=((".txt", "text/plain"),)),
    )
    surface._limiter = LocalAdmission()  # type: ignore[assignment]
    server = AgentOS(
        id="json-output-bounds",
        agents=[agent],
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
    assert int(response.headers["content-length"]) == len(response.content)
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
