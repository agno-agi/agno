"""Wire preservation, safe error handling and retained resolver capacity."""

import asyncio
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from agno.os.public._limits import Admission
from agno.os.public._middleware import PublicMiddleware


class Limiter:
    async def aconsume(self, *args, **kwargs):
        return Admission(True)


def middleware(endpoint, **overrides):
    agent = SimpleNamespace(id="docs")
    surface = SimpleNamespace(
        agents=[agent],
        teams=[],
        workflows=[],
        client_id=None,
        limiter=Limiter(),
        max_active_runs=1,
        max_body_bytes=1000,
        max_run_seconds=1,
        max_output_bytes=1000,
        uploads=None,
        mcp=False,
        **overrides,
    )
    os = SimpleNamespace(agents=[agent], teams=[], workflows=[])
    return PublicMiddleware(endpoint, surface=surface, agent_os=os)


async def invoke(app, body=None, headers=None):
    body = body or urlencode({"message": "How do I handle RunError?", "stream": "true"}).encode()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/agents/docs/runs",
        "query_string": b"",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded"), *(headers or [])],
        "client": ("127.0.0.1", 100),
        "scheme": "http",
        "server": ("testserver", 80),
        "app": SimpleNamespace(state=SimpleNamespace()),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    messages = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


@pytest.mark.asyncio
async def test_sse_mentions_are_preserved_but_actual_errors_are_safe():
    ordinary = b'event: RunContent\ndata: {"event":"RunContent","content":"Use RunError events."}\n\n'
    failure = b'event: RunError\ndata: {"event":"RunError","content":"secret database error"}\n\n'

    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body", "body": ordinary[:30], "more_body": True})
        await send({"type": "http.response.body", "body": ordinary[30:] + failure, "more_body": False})

    app = middleware(endpoint)
    messages = await invoke(app)
    body = b"".join(message.get("body", b"") for message in messages)
    assert body.startswith(ordinary) and b"secret database" not in body
    assert b"correlation_id" in body and app.active_runs == 0


@pytest.mark.asyncio
async def test_safe_errors_keep_authentication_challenges():
    async def endpoint(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"www-authenticate", b'Bearer resource_metadata="https://example.com/metadata"')],
            }
        )
        await send({"type": "http.response.body", "body": b"private diagnostic"})

    messages = await invoke(middleware(endpoint))
    assert messages[0]["status"] == 401
    assert dict(messages[0]["headers"])[b"www-authenticate"].startswith(b"Bearer")
    assert b"private diagnostic" not in messages[-1]["body"]


@pytest.mark.asyncio
async def test_body_and_execution_bounds_release_capacity():
    async def stalled(scope, receive, send):
        await asyncio.sleep(10)

    app = middleware(stalled)
    app.surface.max_run_seconds = 0.01
    assert (await invoke(app))[0]["status"] == 503
    assert app.active_runs == 0
    assert (await invoke(app, body=b"x" * 1001))[0]["status"] == 413
    assert app.active_runs == 0

    async def slow_receive():
        await asyncio.sleep(1)

    with pytest.raises(Exception) as caught:
        await app._body(slow_receive, 100, 0.01)
    assert caught.value.status == 408
