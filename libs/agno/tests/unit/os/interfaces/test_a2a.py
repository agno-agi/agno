"""Unit tests for the A2A interface's stream_a2a_response function.

Regression coverage for: RunCompletedEvent.metadata (e.g. sources, refetch_model
set by a caller's post-processing step) must ride the terminal final=True
status-update event, which the A2A client reads as the run's out-of-band metadata.
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


def _final_status_update(events):
    """Return the terminal final=True status-update event's result."""
    finals = [
        e["result"]
        for e in events
        if e.get("result", {}).get("kind") == "status-update" and e["result"].get("final") is True
    ]
    assert len(finals) == 1
    return finals[0]


class TestStreamA2AResponseMetadata:
    @pytest.mark.asyncio
    async def test_run_completed_metadata_rides_terminal_status_update(self):
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

        final = _final_status_update(events)
        assert final["metadata"] == {"sources": {"llm_sources": []}, "refetch_model": True}

    @pytest.mark.asyncio
    async def test_run_completed_without_metadata_omits_status_metadata_field(self):
        """No metadata set means the terminal status-update's metadata field is
        omitted (exclude_none), not sent as an empty dict."""
        stream = _agent_stream(
            RunStartedEvent(run_id="run-1", session_id="ctx-1"),
            RunContentEvent(content="Hi", run_id="run-1", session_id="ctx-1"),
            RunCompletedEvent(content="Hi", run_id="run-1", session_id="ctx-1"),
        )

        chunks = [chunk async for chunk in stream_a2a_response(stream, request_id="req-1")]
        events = _parse_sse_events("".join(chunks))

        final = _final_status_update(events)
        assert "metadata" not in final
