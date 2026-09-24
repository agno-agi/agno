"""Unit tests for SSEBufferingMiddleware."""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agno.os.middleware.sse_buffering import SSEBufferingMiddleware

ACCEL_HEADER = "X-Accel-Buffering"


async def event_stream():
    """Minimal SSE body."""
    yield "event: ping\n"
    yield "data: {}\n\n"


def sse_handler(request):
    """Streaming endpoint, as used by the AgentOS run routers."""
    return StreamingResponse(event_stream(), media_type="text/event-stream")


def sse_handler_with_header(request):
    """Streaming endpoint that sets the header itself."""
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={ACCEL_HEADER: "yes"},
    )


def json_handler(request):
    """Regular JSON endpoint."""
    return JSONResponse({"status": "ok"})


@pytest.fixture
def app():
    routes = [
        Route("/runs", sse_handler),
        Route("/runs/custom", sse_handler_with_header),
        Route("/agents", json_handler),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(SSEBufferingMiddleware)
    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def test_streaming_response_disables_buffering(client):
    """SSE responses carry X-Accel-Buffering: no."""
    response = client.get("/runs")
    assert response.status_code == 200
    assert response.headers[ACCEL_HEADER] == "no"


def test_streaming_response_body_is_unchanged(client):
    """The middleware does not alter the streamed body."""
    response = client.get("/runs")
    assert "event: ping" in response.text


def test_non_streaming_response_is_untouched(client):
    """JSON responses are not given the header."""
    response = client.get("/agents")
    assert response.status_code == 200
    assert ACCEL_HEADER not in response.headers


def test_explicit_header_wins(client):
    """An endpoint that sets the header itself is not overridden."""
    response = client.get("/runs/custom")
    assert response.headers[ACCEL_HEADER] == "yes"
