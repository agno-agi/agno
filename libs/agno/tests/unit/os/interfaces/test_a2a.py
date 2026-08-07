"""Unit tests for the A2A interface's stream_a2a_response function.

Regression coverage for: RunCompletedEvent.metadata (e.g. sources, refetch_model
set by a caller's post-processing step) must be forwarded onto the final Task's
own metadata field, not just onto the nested agent message inside Task.history -
the A2A client reads Task-level metadata for the "task" kind event.
"""

import json
from typing import AsyncIterator, Union

import pytest

from agno.os.interfaces.a2a.utils import stream_a2a_response
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunStartedEvent


async def _agent_stream(
    *events: Union[RunStartedEvent, RunContentEvent, RunCompletedEvent],
) -> AsyncIterator:
    for event in events:
        yield event


def _parse_sse_events(raw: str):
    """Parse the "event: Name\\ndata: {...}\\n\\n" SSE blocks stream_a2a_response yields."""
    parsed = []
    for block in raw.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        for line in block.split("\n"):
            if line.startswith("data: "):
                parsed.append(json.loads(line[len("data: ") :]))
    return parsed


class TestStreamA2AResponseMetadata:
    @pytest.mark.asyncio
    async def test_run_completed_metadata_forwarded_onto_task(self):
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunContentEvent(content="Hello", run_id="run-1", session_id="ctx-1"),
            RunCompletedEvent(
                content="Hello",
                run_id="run-1",
                session_id="ctx-1",
                metadata={"sources": {"llm_sources": []}, "refetch_model": True},
            ),
        )

        chunks = [chunk async for chunk in stream_a2a_response(stream, request_id="req-1")]
        events = _parse_sse_events("".join(chunks))

        task_events = [e for e in events if e.get("result", {}).get("kind") == "task"]
        assert len(task_events) == 1

        task_result = task_events[0]["result"]
        assert task_result["metadata"] == {"sources": {"llm_sources": []}, "refetch_model": True}

    @pytest.mark.asyncio
    async def test_run_completed_without_metadata_omits_task_metadata_field(self):
        """No metadata set means the Task's metadata field is omitted (exclude_none),
        not sent as an empty dict - avoids ballooning every response with noise."""
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunContentEvent(content="Hi", run_id="run-1", session_id="ctx-1"),
            RunCompletedEvent(content="Hi", run_id="run-1", session_id="ctx-1"),
        )

        chunks = [chunk async for chunk in stream_a2a_response(stream, request_id="req-1")]
        events = _parse_sse_events("".join(chunks))

        task_events = [e for e in events if e.get("result", {}).get("kind") == "task"]
        assert len(task_events) == 1
        assert "metadata" not in task_events[0]["result"]
