"""HTTP-level tests for AG-UI streaming — verifies the wire contract.

These tests drive the FastAPI `attach_routes` endpoint end-to-end with a
stubbed Agent whose `arun` produces a controlled async event stream.
They are the only tests that validate the StreamingResponse actually
closes cleanly on the success path and transmits terminal events (per
the production bug where SSE connections hang open indefinitely).
"""

import asyncio
import json
import threading
from typing import Any, AsyncIterator, List
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os.interfaces.agui import utils as agui_utils
from agno.os.interfaces.agui.router import attach_routes
from agno.run.agent import RunCompletedEvent, RunContentEvent


def _parse_sse(body: str) -> List[dict]:
    """Parse SSE stream body into a list of decoded JSON events.

    Robust against CRLF line endings and multi-line `data:` payloads:
    events are separated by blank lines; within an event, each `data:`
    line is concatenated with `\n` per the SSE spec before JSON decode.

    Skipping rules:
    - Blocks with no `data:` lines at all (pure comment / event-only
      / keepalive blocks) are skipped silently.
    - Blocks whose joined `data:` payload is empty or whitespace-only
      are skipped silently (these are not valid JSON events and are
      not expected from the AGUI translator).
    - Blocks with a non-empty data payload that fails JSON decoding
      fail the test via `pytest.fail` rather than being silently
      dropped — a real malformed event is a wire-contract bug.
    """
    # Normalise CRLF → LF, then split on blank-line event separators.
    normalised = body.replace("\r\n", "\n").replace("\r", "\n")
    blocks = normalised.split("\n\n")
    events: List[dict] = []
    for block in blocks:
        data_lines: List[str] = []
        for line in block.split("\n"):
            if line.startswith("data:"):
                # Strip the single leading space after `data:` if present
                # (per SSE spec) but preserve any further whitespace.
                payload = line[5:]
                if payload.startswith(" "):
                    payload = payload[1:]
                data_lines.append(payload)
        if not data_lines:
            continue
        joined = "\n".join(data_lines)
        if not joined.strip():
            continue
        try:
            events.append(json.loads(joined))
        except json.JSONDecodeError as e:
            pytest.fail(f"Malformed SSE event payload: {joined!r} ({e})")
    return events


def _build_app(agent):
    from fastapi.routing import APIRouter

    router = APIRouter()
    attach_routes(router=router, agent=agent)
    app = FastAPI()
    app.include_router(router)
    return app


def _make_agent_stub(events: List[Any]):
    """Create a MagicMock agent whose arun returns a fresh async iterator each call.

    The AGUI router calls `agent.arun(...)` once per request and iterates
    the returned async generator via `async for`. Using `side_effect` with
    a factory ensures each call produces a new iterator (a `return_value`
    would exhaust on the second call under any retry/repeat code path).
    """

    async def async_iter() -> AsyncIterator[Any]:
        for ev in events:
            yield ev

    agent = MagicMock(spec=Agent)
    agent.arun = MagicMock(side_effect=lambda *a, **kw: async_iter())
    return agent


def test_agui_success_path_emits_run_finished_and_closes():
    """
    Reproduces the production bug: on a SUCCESSFUL agent run, the AGUI
    StreamingResponse must emit a RUN_FINISHED terminal event and close
    the connection. Production observed TTFB + partial events followed
    by indefinite hang (curl exit 28 timeout, zero RUN_FINISHED).
    """
    # Simulated successful stream: started → content → completed.
    events = [
        RunContentEvent(content="Hello "),
        RunContentEvent(content="world"),
        RunCompletedEvent(content="Hello world"),
    ]
    agent = _make_agent_stub(events)
    app = _build_app(agent)

    with TestClient(app) as client:
        response = client.post(
            "/agui",
            json={
                "thread_id": "t-1",
                "run_id": "r-1",
                "state": {},
                "messages": [{"id": "m-1", "role": "user", "content": "Say hello"}],
                "tools": [],
                "context": [],
                "forwarded_props": {},
            },
        )

    assert response.status_code == 200, response.text
    body = response.text
    parsed = _parse_sse(body)

    types = [e.get("type") for e in parsed]

    assert types, f"No SSE events emitted. Raw body: {body!r}"
    assert types[0] == "RUN_STARTED", f"First event must be RUN_STARTED, got {types}"
    assert "TEXT_MESSAGE_START" in types, f"Missing TEXT_MESSAGE_START, got {types}"
    assert "TEXT_MESSAGE_CONTENT" in types, f"Missing TEXT_MESSAGE_CONTENT, got {types}"
    assert "TEXT_MESSAGE_END" in types, f"Missing TEXT_MESSAGE_END, got {types}"
    assert types[-1] == "RUN_FINISHED", f"Last event must be RUN_FINISHED (terminal event). Got sequence: {types}"


def test_agui_success_path_no_run_started_from_agent_still_terminates():
    """
    If agent.arun only yields content + completion (no RunStartedEvent),
    the router synthesizes RUN_STARTED and the utils layer emits
    RUN_FINISHED. Stream must still terminate.
    """
    events = [
        RunContentEvent(content="Hi"),
        RunCompletedEvent(content="Hi"),
    ]
    agent = _make_agent_stub(events)
    app = _build_app(agent)

    with TestClient(app) as client:
        response = client.post(
            "/agui",
            json={
                "thread_id": "t-2",
                "run_id": "r-2",
                "state": {},
                "messages": [{"id": "m-1", "role": "user", "content": "Hi"}],
                "tools": [],
                "context": [],
                "forwarded_props": {},
            },
        )

    assert response.status_code == 200
    parsed = _parse_sse(response.text)
    types = [e.get("type") for e in parsed]
    assert types[-1] == "RUN_FINISHED", types


def test_agui_success_path_terminates_after_run_completed_even_if_iterator_lingers():
    """
    Hypothesis: the agent's async iterator yields `run_completed` but does
    NOT terminate immediately — it has additional await points (background
    cleanup, telemetry flush, session DB write) that keep the iterator
    alive. The AGUI loop has no early-exit on `run_completed`, so it sits
    in `async for` until those cleanup awaits resolve (or never).

    This test simulates that shape: after `RunCompletedEvent`, the iterator
    awaits an event that never fires. Expected behavior: AGUI emits
    RUN_FINISHED and terminates the SSE response without waiting for
    post-completion iterator cleanup.
    """

    async def hanging_after_complete() -> AsyncIterator[Any]:
        yield RunContentEvent(content="Hello")
        yield RunCompletedEvent(content="Hello")
        # Simulate iterator that doesn't cleanly terminate after completion.
        await asyncio.Event().wait()  # Never resolves.
        yield RunContentEvent(content="unreachable")  # pragma: no cover

    agent = MagicMock(spec=Agent)
    # `side_effect` factory — each call produces a fresh async generator.
    agent.arun = MagicMock(side_effect=lambda *a, **kw: hanging_after_complete())
    app = _build_app(agent)

    with TestClient(app) as client:
        result: dict = {}

        def _run():
            try:
                result["response"] = client.post(
                    "/agui",
                    json={
                        "thread_id": "t-hang",
                        "run_id": "r-hang",
                        "state": {},
                        "messages": [{"id": "m-1", "role": "user", "content": "Hi"}],
                        "tools": [],
                        "context": [],
                        "forwarded_props": {},
                    },
                )
            except Exception as e:
                result["error"] = e

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=8.0)

        # A still-alive worker thread indicates the SSE response never
        # closed — the exact production symptom.
        if t.is_alive():
            pytest.fail(
                "AGUI SSE response hung after agent emitted RUN_COMPLETED "
                "— matches the production symptom of SSE connections not "
                "closing after a successful run."
            )

        assert "response" in result, f"Request failed: {result.get('error')!r}"
        response = result["response"]

    assert response.status_code == 200
    parsed = _parse_sse(response.text)
    types = [e.get("type") for e in parsed]
    assert types[-1] == "RUN_FINISHED", f"Expected RUN_FINISHED as last event after RunCompletedEvent. Got: {types}"


def test_agui_stream_with_no_completion_event_still_terminates():
    """
    Even if the agent stream ends naturally without RunCompletedEvent,
    the async generator must emit a synthetic RUN_FINISHED.
    """
    events = [
        RunContentEvent(content="partial"),
        # No RunCompletedEvent — stream ends naturally.
    ]
    agent = _make_agent_stub(events)
    app = _build_app(agent)

    with TestClient(app) as client:
        response = client.post(
            "/agui",
            json={
                "thread_id": "t-3",
                "run_id": "r-3",
                "state": {},
                "messages": [{"id": "m-1", "role": "user", "content": "Hi"}],
                "tools": [],
                "context": [],
                "forwarded_props": {},
            },
        )

    assert response.status_code == 200
    parsed = _parse_sse(response.text)
    types = [e.get("type") for e in parsed]
    assert types[-1] == "RUN_FINISHED", f"Synthetic RUN_FINISHED expected, got {types}"


@pytest.mark.asyncio
async def test_async_stream_logs_warning_when_aclose_raises(monkeypatch):
    """If the upstream iterator's aclose() raises, the AGUI translator
    must log a warning (not silently swallow) so production bugs in
    upstream cleanup code are visible. Terminal RUN_FINISHED must still
    be emitted to the client — aclose failure is non-fatal.

    Directly monkeypatches the `log_warning` reference used inside
    `agno.os.interfaces.agui.utils` rather than relying on pytest's
    `caplog`, because agno wires its own RichHandler and the default
    caplog capture does not always intercept it.
    """
    captured: List[str] = []

    def _fake_log_warning(msg, *args, **kwargs):
        captured.append(str(msg))

    monkeypatch.setattr(agui_utils, "log_warning", _fake_log_warning)

    class FailingAclose:
        """Async-iterator wrapper whose aclose() raises."""

        def __init__(self, events):
            self._events = iter(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._events)
            except StopIteration:
                raise StopAsyncIteration

        async def aclose(self):
            raise RuntimeError("synthetic aclose failure")

    stream = FailingAclose(
        [
            RunContentEvent(content="Hello"),
            RunCompletedEvent(content="Hello"),
        ]
    )

    async def drain():
        out = []
        async for ev in agui_utils.async_stream_agno_response_as_agui_events(
            response_stream=stream, thread_id="t", run_id="r"
        ):
            out.append(ev)
        return out

    events = await drain()

    # Terminal event must still be emitted even though aclose raised.
    types = [getattr(e, "type", None) for e in events]
    type_values = [t.value if hasattr(t, "value") else t for t in types]
    assert "RUN_FINISHED" in type_values, f"aclose failure must not prevent RUN_FINISHED emission; got {types}"

    # Warning must be emitted so upstream cleanup failures are visible.
    assert any("aclose" in m and "synthetic aclose failure" in m for m in captured), (
        f"Expected a warning mentioning aclose() + the synthetic error; got {captured!r}"
    )


@pytest.mark.asyncio
async def test_async_stream_aclose_hang_does_not_block_terminal_event(monkeypatch):
    """Round 2 / finding #1: if the upstream iterator's aclose() hangs
    (e.g. nested try/finally with telemetry flush / DB close that awaits
    indefinitely), `await response_stream.aclose()` re-introduces the
    exact hang this PR fixes — `aclose()` throws GeneratorExit into the
    generator and awaits its cleanup path.

    Fix: `aclose()` must be bounded by a short timeout. On timeout, a
    warning is logged and terminal-event emission continues.

    Test: replace aclose with `await asyncio.Event().wait()` (never
    resolves). The test runs the async generator with a wall-clock
    deadline and asserts RUN_FINISHED is emitted inside that budget.
    """
    captured: List[str] = []

    def _fake_log_warning(msg, *args, **kwargs):
        captured.append(str(msg))

    monkeypatch.setattr(agui_utils, "log_warning", _fake_log_warning)

    class HangingAclose:
        """Async-iterator wrapper whose aclose() awaits forever."""

        def __init__(self, events):
            self._events = iter(events)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._events)
            except StopIteration:
                raise StopAsyncIteration

        async def aclose(self):
            await asyncio.Event().wait()  # Never resolves.

    stream = HangingAclose(
        [
            RunContentEvent(content="Hello"),
            RunCompletedEvent(content="Hello"),
        ]
    )

    async def drain():
        out = []
        async for ev in agui_utils.async_stream_agno_response_as_agui_events(
            response_stream=stream, thread_id="t-hang-aclose", run_id="r-hang-aclose"
        ):
            out.append(ev)
        return out

    # Bound the whole drain call. If aclose blocks the generator, this
    # outer wait_for fires and the test fails; the fix's internal
    # wait_for should prevent that and complete well under this budget.
    events = await asyncio.wait_for(drain(), timeout=5.0)

    types = [getattr(e, "type", None) for e in events]
    type_values = [t.value if hasattr(t, "value") else t for t in types]
    assert "RUN_FINISHED" in type_values, f"Hanging aclose() must not block RUN_FINISHED emission; got {types}"

    # Warning must be emitted so hanging aclose is visible in logs.
    assert any("aclose" in m and ("timed out" in m or "timeout" in m.lower()) for m in captured), (
        f"Expected a warning mentioning aclose() timeout; got {captured!r}"
    )

    # Correlation IDs must be present in the warning (finding #3).
    assert any("t-hang-aclose" in m and "r-hang-aclose" in m for m in captured), (
        f"Expected thread_id/run_id in aclose warning; got {captured!r}"
    )


@pytest.mark.asyncio
async def test_async_stream_propagates_exception_without_synthetic_completion(monkeypatch):
    """Round 2 / finding #2: if the `async for` loop raises (e.g. the
    upstream agent's iterator errors mid-stream), the translator must
    NOT emit a synthetic `RunCompletedEvent` that masks the failure —
    the original exception must propagate to the caller and no
    `RUN_FINISHED` must be yielded.
    """

    class RaisingIterator:
        def __init__(self, events, exc):
            self._events = iter(events)
            self._exc = exc
            self.aclose_called = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._events)
            except StopIteration:
                # After yielding events, raise instead of StopAsyncIteration.
                raise self._exc

        async def aclose(self):
            self.aclose_called = True

    synthetic_error = RuntimeError("agent iterator blew up")
    stream = RaisingIterator(
        [
            RunContentEvent(content="partial"),
        ],
        synthetic_error,
    )

    collected: List[Any] = []

    async def drain():
        async for ev in agui_utils.async_stream_agno_response_as_agui_events(
            response_stream=stream, thread_id="t-err", run_id="r-err"
        ):
            collected.append(ev)

    with pytest.raises(RuntimeError, match="agent iterator blew up"):
        await drain()

    # aclose must still have run (finally cleanup).
    assert stream.aclose_called, "aclose() must still be invoked via finally on exception path"

    # Synthetic RUN_FINISHED MUST NOT be emitted on the exception path —
    # emitting a terminal "success" event would mask the failure from
    # downstream clients. Any events emitted before the exception are
    # fine; the terminal RUN_FINISHED is the load-bearing check.
    types = [getattr(e, "type", None) for e in collected]
    type_values = [t.value if hasattr(t, "value") else t for t in types]
    assert "RUN_FINISHED" not in type_values, (
        f"Exception path must not emit synthetic RUN_FINISHED (masks failure); got {types}"
    )
