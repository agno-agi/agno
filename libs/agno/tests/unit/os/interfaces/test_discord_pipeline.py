"""Unit tests for the shared Discord pipeline: discord_request rate-limit
handling and stream_agent_run status debouncing."""

from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest

from agno.os.interfaces.discord.pipeline import (
    MAX_RATE_LIMIT_RETRIES,
    STATUS_THINKING,
    discord_request,
    stream_agent_run,
)
from agno.run.agent import RunOutput


class FakeClient:
    """httpx.AsyncClient stand-in that pops canned responses (or raises)."""

    def __init__(self, outcomes: List[Any]):
        self.outcomes = outcomes
        self.calls = 0

    async def request(self, method: str, url: str, headers=None, json=None) -> httpx.Response:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def rate_limited(retry_after: str = "0") -> httpx.Response:
    return httpx.Response(429, headers={"Retry-After": retry_after}, json={"message": "rate limited"})


@pytest.mark.asyncio
async def test_discord_request_retries_429_until_success():
    client = FakeClient([rate_limited(), rate_limited(), httpx.Response(200, json={"id": "1"})])
    resp = await discord_request(client, "POST", "https://x/y")  # type: ignore[arg-type]
    assert resp is not None
    assert resp.status_code == 200
    assert client.calls == 3


@pytest.mark.asyncio
async def test_discord_request_gives_up_after_max_retries():
    client = FakeClient([rate_limited()])
    resp = await discord_request(client, "POST", "https://x/y")  # type: ignore[arg-type]
    assert resp is not None
    assert resp.status_code == 429
    assert client.calls == MAX_RATE_LIMIT_RETRIES + 1


@pytest.mark.asyncio
async def test_discord_request_honors_retry_after_header():
    client = FakeClient([rate_limited(retry_after="2.5"), httpx.Response(200)])
    with patch("agno.os.interfaces.discord.pipeline.asyncio.sleep") as sleep:
        resp = await discord_request(client, "POST", "https://x/y")  # type: ignore[arg-type]
    assert resp is not None and resp.status_code == 200
    sleep.assert_awaited_once_with(2.5)


@pytest.mark.asyncio
async def test_discord_request_returns_none_on_transport_error():
    client = FakeClient([httpx.ConnectError("boom")])
    resp = await discord_request(client, "POST", "https://x/y")  # type: ignore[arg-type]
    assert resp is None


@pytest.mark.asyncio
async def test_discord_request_does_not_retry_other_errors():
    client = FakeClient([httpx.Response(403, json={"message": "no"})])
    resp = await discord_request(client, "POST", "https://x/y")  # type: ignore[arg-type]
    assert resp is not None
    assert resp.status_code == 403
    assert client.calls == 1


class FakeTool:
    def __init__(self, tool_name: str, tool_call_id: str):
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id


class FakeEvent:
    def __init__(self, event: str, tool: FakeTool):
        self.event = event
        self.tool = tool


class FakeEntity:
    """Yields a scripted event sequence, then the final RunOutput."""

    def __init__(self, events: List[Any]):
        self.events = events

    async def arun(self, message: str, **kwargs):
        for event in self.events:
            yield event


@pytest.mark.asyncio
async def test_stream_agent_run_debounces_rapid_status_edits():
    events = [
        FakeEvent("ToolCallStarted", FakeTool("search", "c1")),  # shown (first status, clock exempt)
        FakeEvent("ToolCallCompleted", FakeTool("search", "c1")),  # 0.5s later -> debounced
        FakeEvent("ToolCallStarted", FakeTool("scrape", "c2")),  # 2.0s later -> shown
        RunOutput(content="the answer"),
    ]
    clock = {"now": 100.0}
    ticks = iter([100.0, 100.5, 102.0])

    edits: List[str] = []

    async def status_edit(content: str) -> None:
        edits.append(content)

    def fake_monotonic() -> float:
        return clock["now"]

    entity = FakeEntity(events)

    original_events = entity.events

    async def arun_with_clock(message: str, **kwargs):
        for event in original_events:
            if isinstance(event, FakeEvent):
                clock["now"] = next(ticks)
            yield event

    entity.arun = arun_with_clock  # type: ignore[method-assign]

    with patch("agno.os.interfaces.discord.pipeline.time.monotonic", fake_monotonic):
        media: Dict[str, Any] = {}
        result = await stream_agent_run(entity, "q", "u1", "s1", media, {}, status_edit)

    assert result == "the answer"
    assert edits == [STATUS_THINKING, "Running tool: search...", "Running tool: scrape..."]


@pytest.mark.asyncio
async def test_stream_agent_run_returns_placeholder_for_empty_content():
    entity = FakeEntity([RunOutput(content="")])

    async def status_edit(content: str) -> None:
        pass

    result = await stream_agent_run(entity, "q", "u1", "s1", {}, {}, status_edit)
    assert result == "(empty response)"
