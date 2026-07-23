"""
REPRODUCTION TEST: Context Provider Streaming Duplication Bug

This test exercises the REAL code path to verify content doesn't appear twice.
It creates a minimal provider with a fake agent that emits controllable events,
simulating exactly what happens when an agent calls a context provider tool.

The bug was:
    function_call_output = 'Hello world{"text": "Hello world"}'

Expected after fix:
    function_call_output = 'Hello world'
"""

from __future__ import annotations

import json
from typing import get_args

import pytest

from agno.context import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.run.agent import (
    RunContentEvent,
    RunOutput,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)


class FakeStreamingAgent:
    """A fake agent that yields controllable events for testing."""

    def __init__(self, content: str):
        self.content = content

    async def arun(self, message: str, **kwargs):
        """Simulate agent streaming: events + final RunOutput."""
        yield ToolCallStartedEvent()

        # Stream content word by word
        words = self.content.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == len(words) - 1 else word + " "
            yield RunContentEvent(content=chunk)

        yield ToolCallCompletedEvent()
        yield RunOutput(content=self.content)


class ReproductionProvider(ContextProvider):
    """A real provider using the fake streaming agent."""

    def __init__(self, content: str = "The quick brown fox", **kwargs):
        super().__init__(**kwargs)
        self.content = content

    def status(self) -> Status:
        return Status(ok=True, detail="test provider")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=self.content)

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=self.content)

    async def _aget_query_agent(self, run_context: RunContext | None):
        return FakeStreamingAgent(self.content)


def simulate_base_py_accumulation(chunks: list) -> str:
    """Simulate EXACTLY what models/base.py:2730-2767 does."""
    from pydantic import BaseModel

    function_call_output = ""

    for item in chunks:
        if isinstance(item, tuple(get_args(RunOutputEvent))):
            if isinstance(item, RunContentEvent):
                if item.content is not None and isinstance(item.content, BaseModel):
                    function_call_output += item.content.model_dump_json()
                else:
                    function_call_output += item.content or ""
        else:
            function_call_output += str(item)

    return function_call_output


@pytest.mark.asyncio
async def test_streaming_reproduction_no_duplication():
    """
    REPRODUCTION TEST: Verify the actual code path doesn't duplicate content.

    If the bug returns, this test will fail with:
        AssertionError: DUPLICATION DETECTED!
        Got: 'The quick brown fox{"text": "The quick brown fox"}'
    """
    provider = ReproductionProvider(id="repro", stream_sub_agent_events=True)
    query_tool = provider._query_tool()

    gen = await query_tool.entrypoint(question="What does the fox say?")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    result = simulate_base_py_accumulation(chunks)

    expected = "The quick brown fox"
    buggy_pattern = f'{expected}{{"text": "{expected}"}}'

    assert result != buggy_pattern, f"DUPLICATION DETECTED!\nGot: '{result}'\nThe bug is back."

    assert result == expected, f"Content mismatch!\nExpected: '{expected}'\nGot: '{result}'"


@pytest.mark.asyncio
async def test_streaming_no_json_strings_yielded():
    """Streaming mode should NOT yield any JSON strings."""
    provider = ReproductionProvider(id="repro", stream_sub_agent_events=True)
    query_tool = provider._query_tool()

    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    json_strings = [c for c in chunks if isinstance(c, str)]
    assert len(json_strings) == 0, f"Found JSON strings: {json_strings}"


class FallbackProvider(ContextProvider):
    """Provider that falls back to aquery (no sub-agent)."""

    def __init__(self, content: str = "The quick brown fox", **kwargs):
        super().__init__(**kwargs)
        self.content = content

    def status(self) -> Status:
        return Status(ok=True, detail="test")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=self.content)

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=self.content)

    async def _aget_query_agent(self, run_context: RunContext | None):
        return None


@pytest.mark.asyncio
async def test_non_streaming_yields_single_json():
    """Non-streaming mode yields exactly one JSON answer."""
    provider = FallbackProvider(id="repro", stream_sub_agent_events=False)
    query_tool = provider._query_tool()

    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
    assert isinstance(chunks[0], str)

    payload = json.loads(chunks[0])
    assert payload["text"] == "The quick brown fox"


@pytest.mark.asyncio
async def test_streaming_yields_expected_event_types():
    """Verify streaming yields events, not Answer objects."""
    provider = ReproductionProvider(id="repro", stream_sub_agent_events=True)
    query_tool = provider._query_tool()

    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    event_types = {type(c).__name__ for c in chunks}

    assert "RunContentEvent" in event_types
    assert "Answer" not in event_types
    assert "RunOutput" not in event_types


@pytest.mark.asyncio
async def test_parent_run_id_set():
    """Verify parent_run_id is propagated to events."""
    provider = ReproductionProvider(id="repro", stream_sub_agent_events=True)
    query_tool = provider._query_tool()

    run_context = RunContext(run_id="parent-123", user_id="u", session_id="s")
    gen = await query_tool.entrypoint(question="test", run_context=run_context)

    events_with_parent_id = []
    async for chunk in gen:
        if hasattr(chunk, "parent_run_id"):
            events_with_parent_id.append(chunk)

    assert len(events_with_parent_id) > 0
    for event in events_with_parent_id:
        assert event.parent_run_id == "parent-123"
