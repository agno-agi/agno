"""Wire preservation, safe error handling and retained resolver capacity."""

import asyncio
import json
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


async def invoke(app, body=None, headers=None, messages=None):
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

    messages = [] if messages is None else messages

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


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [-1, 0, 1])
@pytest.mark.parametrize("fragmented", [False, True])
async def test_json_is_validated_before_success_headers_and_preserves_boundaries(delta, fragmented):
    from agno.os.public import get_public_client_id

    maximum = 1000
    payload = b'{"content":"' + b"x" * (maximum + delta - len(b'{"content":""}')) + b'"}'
    parts = [payload[:11], b"", payload[11:999], payload[999:], b""] if fragmented else [payload]
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
        (b"x-original-response", b"keep-on-success"),
    ]
    messages, cleaned = [], []

    async def endpoint(scope, receive, send):
        try:
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            assert not messages
            for index, part in enumerate(parts):
                more = index < len(parts) - 1
                await send({"type": "http.response.body", "body": part, "more_body": more})
                if more:
                    assert not messages
        finally:
            cleaned.append(True)

    app = middleware(endpoint)
    await invoke(app, body=urlencode({"message": "hello", "stream": "false"}).encode(), messages=messages)
    assert len(messages) == 2 and not messages[-1].get("more_body", False)
    body = messages[-1]["body"]
    sent_headers = dict(messages[0]["headers"])
    assert int(sent_headers[b"content-length"]) == len(body)
    if delta <= 0:
        assert messages[0]["status"] == 200
        assert messages[0]["headers"] == headers and body == payload
    else:
        assert messages[0]["status"] == 503
        assert sent_headers[b"content-type"] == b"application/json"
        assert b"x-original-response" not in sent_headers
        assert json.loads(body)["error"]["code"] == "output_limit"
        assert len(json.loads(body)["error"]["correlation_id"]) == 32
        assert b"xxxxxxxx" not in body
    assert cleaned == [True] and app.active_runs == 0
    assert get_public_client_id() == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "timeout", "cancel"])
async def test_partial_json_failure_discards_success_and_releases_capacity(failure):
    entered, cleaned = asyncio.Event(), asyncio.Event()
    messages = []

    async def endpoint(scope, receive, send):
        try:
            await send(
                {"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]}
            )
            await send({"type": "http.response.body", "body": b'{"private":"diagnostic', "more_body": True})
            assert not messages
            entered.set()
            if failure == "error":
                raise RuntimeError("private diagnostic")
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    app = middleware(endpoint)
    if failure == "timeout":
        app.surface.max_run_seconds = 0.05
    task = asyncio.create_task(invoke(app, messages=messages))
    await asyncio.wait_for(entered.wait(), 1)
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert messages == []
    else:
        await task
        assert len(messages) == 2 and messages[0]["status"] == 503
        assert json.loads(messages[-1]["body"])["error"]["code"] == "service_unavailable"
        assert b"private" not in messages[-1]["body"]
    assert cleaned.is_set() and app.active_runs == 0
