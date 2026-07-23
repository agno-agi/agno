"""Regression tests for content duplication bug in context provider streaming.

This file contains bulletproof tests that simulate EXACTLY what models/base.py
does when processing async generator tool results. The bug was that context
providers yielded both RunContentEvent deltas AND a final JSON answer, causing
content to appear twice in function_call_output.

Example of the bug (before fix):
    function_call_output = 'Hello world{"text": "Hello world"}'

Expected (after fix):
    function_call_output = 'Hello world'

The fix matches the Team pattern where delegate_task_to_member yields only
events when streaming (gated by `if not stream:` at team/_default_tools.py:736).
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


class _TestProvider(ContextProvider):
    """Test provider that returns fixed content via streaming sub-agent."""

    def __init__(self, content: str = "Hello world", **kwargs):
        super().__init__(**kwargs)
        self._content = content

    def status(self) -> Status:
        return Status(ok=True, detail="test")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=self._content)

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return Answer(text=self._content)

    async def _aget_query_agent(self, run_context):
        content = self._content

        class _FakeAgent:
            async def arun(self, message, **kwargs):
                # Simulate realistic streaming with multiple event types
                yield ToolCallStartedEvent()

                # Stream content in chunks (like real LLM)
                words = content.split(" ")
                for i, word in enumerate(words):
                    chunk = word if i == len(words) - 1 else word + " "
                    yield RunContentEvent(content=chunk)

                yield ToolCallCompletedEvent()
                yield RunOutput(content=content)

        return _FakeAgent()

    async def _aget_update_agent(self, run_context):
        return await self._aget_query_agent(run_context)


def _simulate_base_py_accumulation(chunks: list) -> str:
    """Simulate EXACTLY what models/base.py:2730-2767 does.

    This is the critical logic that caused the duplication bug.
    We replicate it here to ensure our fix works correctly.
    """
    from pydantic import BaseModel

    function_call_output = ""

    for item in chunks:
        # Check if it's a run/team/workflow event (base.py:2730-2735)
        if isinstance(item, tuple(get_args(RunOutputEvent))):
            # Only RunContentEvent contributes to output (base.py:2737-2742)
            if isinstance(item, RunContentEvent):
                if item.content is not None and isinstance(item.content, BaseModel):
                    function_call_output += item.content.model_dump_json()
                else:
                    function_call_output += item.content or ""
            # Other events are forwarded but don't contribute to output
        else:
            # Non-event items (strings) are appended directly (base.py:2766-2767)
            function_call_output += str(item)

    return function_call_output


# ---------------------------------------------------------------------------
# Core regression tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_no_duplication_simple():
    """Simple case: content should appear exactly once."""
    p = _TestProvider(id="test", content="Hello world")
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    result = _simulate_base_py_accumulation(chunks)

    assert result == "Hello world", (
        f"Content duplicated! Got: '{result}'\nIf you see 'Hello world{{\"text\": \"Hello world\"}}', the bug is back."
    )


@pytest.mark.asyncio
async def test_streaming_no_duplication_multiword():
    """Multi-word content streamed in chunks."""
    content = "The quick brown fox jumps over the lazy dog"
    p = _TestProvider(id="test", content=content)
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    result = _simulate_base_py_accumulation(chunks)

    assert result == content, f"Content duplicated! Got: '{result}'"


@pytest.mark.asyncio
async def test_streaming_no_json_in_output():
    """Streaming mode should NOT yield JSON strings."""
    p = _TestProvider(id="test", content="Test content")
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    # Check no JSON strings were yielded
    json_strings = [c for c in chunks if isinstance(c, str)]
    assert len(json_strings) == 0, f"Streaming mode should not yield JSON strings!\nFound: {json_strings}"


@pytest.mark.asyncio
async def test_streaming_no_answer_object():
    """Streaming mode should NOT yield Answer objects."""
    p = _TestProvider(id="test", content="Test content")
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    # Check no Answer objects were yielded
    answers = [c for c in chunks if isinstance(c, Answer)]
    assert len(answers) == 0, f"Streaming mode should not yield Answer objects!\nFound: {answers}"


@pytest.mark.asyncio
async def test_non_streaming_yields_json_once():
    """Non-streaming mode yields single JSON answer."""

    class _NonStreamingProvider(_TestProvider):
        async def _aget_query_agent(self, run_context):
            content = self._content

            class _FakeAgent:
                async def arun(self, message, **kwargs):
                    return RunOutput(content=content)

            return _FakeAgent()

    p = _NonStreamingProvider(id="test", content="Hello world", stream_sub_agent_events=False)
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    assert len(chunks) == 1, f"Non-streaming should yield exactly 1 item, got {len(chunks)}"
    assert isinstance(chunks[0], str), f"Should be JSON string, got {type(chunks[0])}"

    payload = json.loads(chunks[0])
    assert payload == {"text": "Hello world"}


@pytest.mark.asyncio
async def test_update_tool_streaming_no_duplication():
    """Update tool also shouldn't duplicate content."""
    p = _TestProvider(id="test", content="Created file")
    update_tool = p._update_tool()
    gen = await update_tool.entrypoint(instruction="create")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    result = _simulate_base_py_accumulation(chunks)

    assert result == "Created file", f"Update tool duplicated content! Got: '{result}'"


@pytest.mark.asyncio
async def test_detects_duplication_pattern():
    """Verify we can detect the exact duplication pattern that was the bug."""
    # This is what the buggy output looked like
    buggy_output = 'Hello world{"text": "Hello world"}'

    # Check for the duplication pattern
    has_json = '{"text":' in buggy_output
    content_before_json = buggy_output.split('{"text":')[0] if has_json else ""

    assert has_json, "Test setup error: should have JSON"
    assert content_before_json == "Hello world", "Test setup error"

    # Now verify our fix doesn't produce this pattern
    p = _TestProvider(id="test", content="Hello world")
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    result = _simulate_base_py_accumulation(chunks)

    # The fix should NOT have JSON in the output
    assert '{"text":' not in result, (
        f"DUPLICATION BUG DETECTED!\nOutput contains JSON that shouldn't be there: '{result}'"
    )


@pytest.mark.asyncio
async def test_parent_run_id_set_on_all_events():
    """All events should have parent_run_id set."""
    p = _TestProvider(id="test", content="Test")
    query_tool = p._query_tool()
    rc = RunContext(run_id="parent-123", user_id="u", session_id="s")
    gen = await query_tool.entrypoint(question="test", run_context=rc)

    events = []
    async for chunk in gen:
        if not isinstance(chunk, str):
            events.append(chunk)

    assert len(events) > 0, "Should have yielded some events"

    for event in events:
        assert getattr(event, "parent_run_id", None) == "parent-123", (
            f"Event {type(event).__name__} missing parent_run_id"
        )


@pytest.mark.asyncio
async def test_special_characters_in_content():
    """Content with special characters (quotes, newlines) handled correctly."""
    content = 'Line 1\nLine 2\n"quoted text"\n{not json}'
    p = _TestProvider(id="test", content=content)
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    result = _simulate_base_py_accumulation(chunks)

    assert result == content, f"Special characters mangled! Got: '{result}'"


@pytest.mark.asyncio
async def test_empty_content():
    """Empty content handled correctly."""
    p = _TestProvider(id="test", content="")
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    result = _simulate_base_py_accumulation(chunks)

    assert result == "", f"Empty content should produce empty result, got: '{result}'"


@pytest.mark.asyncio
async def test_unicode_content():
    """Unicode content (emojis, non-ASCII) handled correctly."""
    content = "Hello 世界 🌍 مرحبا"
    p = _TestProvider(id="test", content=content)
    query_tool = p._query_tool()
    gen = await query_tool.entrypoint(question="test")

    chunks = []
    async for chunk in gen:
        chunks.append(chunk)

    result = _simulate_base_py_accumulation(chunks)

    assert result == content, f"Unicode content mangled! Got: '{result}'"
