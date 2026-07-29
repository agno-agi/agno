"""Deterministic offline model for load testing the job queue.

No network, no cost. Latency and (optional) failure are controlled by the run
input so scenarios are reproducible:
    "sleep=2.5"        -> takes ~2.5s then returns canned content
    "fail"             -> raises, to exercise ERROR/retry paths
    "sleep=8 cpu"      -> busy-loops (GIL starvation test for heartbeat)
Anything else -> ~0.5s default.

Mirrors libs/agno/tests/unit/agent/test_dependencies_merge.py:MockModel.
"""

import asyncio
import re
import time
from typing import Any, AsyncIterator, Iterator
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse

_SLEEP = re.compile(r"sleep=([0-9.]+)")


def _plan(messages: Any) -> tuple[float, bool, bool]:
    """Return (latency_seconds, should_fail, cpu_bound) parsed from the last user message."""
    text = ""
    try:
        for m in reversed(messages or []):
            content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
            if content:
                text = str(content)
                break
    except Exception:
        pass
    latency = 0.5
    match = _SLEEP.search(text)
    if match:
        latency = min(float(match.group(1)), 30.0)
    return latency, ("fail" in text), ("cpu" in text)


class LatencyModel(Model):
    """Offline model with input-controlled latency/failure."""

    def __init__(self) -> None:
        super().__init__(id="latency-stub", name="latency-stub", provider="test")
        self.instructions = None
        self._resp = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *a, **k):
        return None

    def get_system_message_for_model(self, *a, **k):
        return None

    async def aget_instructions_for_model(self, *a, **k):
        return None

    async def aget_system_message_for_model(self, *a, **k):
        return None

    def parse_args(self, *a, **k):
        return {}

    def _sleep_sync(self, messages):
        latency, should_fail, cpu = _plan(messages)
        if cpu:
            end = time.time() + latency
            while time.time() < end:
                pass  # busy-loop: starve the event loop
        else:
            time.sleep(latency)
        if should_fail:
            raise RuntimeError("stub-model-induced failure")

    async def _sleep_async(self, messages):
        latency, should_fail, cpu = _plan(messages)
        if cpu:
            end = time.time() + latency
            while time.time() < end:
                pass
        else:
            await asyncio.sleep(latency)
        if should_fail:
            raise RuntimeError("stub-model-induced failure")

    def invoke(self, *a, **k) -> ModelResponse:
        self._sleep_sync(k.get("messages") or (a[0] if a else None))
        return self._resp

    async def ainvoke(self, *a, **k) -> ModelResponse:
        await self._sleep_async(k.get("messages") or (a[0] if a else None))
        return self._resp

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        self._sleep_sync(k.get("messages") or (a[0] if a else None))
        yield self._resp

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        await self._sleep_async(k.get("messages") or (a[0] if a else None))
        yield self._resp
        return

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return self._resp

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._resp
