import json

import pytest
from pydantic import BaseModel

from agno.os.interfaces.a2a.utils import stream_a2a_response
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunStartedEvent


class AnalysisResult(BaseModel):
    category: str
    confidence: float


def _extract_sse_payload(chunks: list[str], event_name: str) -> dict:
    for chunk in chunks:
        if chunk.startswith(f"event: {event_name}\n"):
            data_line = next(line for line in chunk.splitlines() if line.startswith("data: "))
            return json.loads(data_line.removeprefix("data: "))
    raise AssertionError(f"event {event_name} not found")


@pytest.mark.asyncio
async def test_stream_a2a_response_serializes_pydantic_content_events() -> None:
    structured = AnalysisResult(category="security", confidence=0.93)

    async def event_stream():
        yield RunStartedEvent(run_id="run-1", session_id="sess-1")
        yield RunContentEvent(content=structured)
        yield RunCompletedEvent(content=structured)

    chunks = [chunk async for chunk in stream_a2a_response(event_stream(), request_id="req-1")]

    message_payload = _extract_sse_payload(chunks, "Message")
    final_task_payload = _extract_sse_payload(chunks, "Task")

    message_text = message_payload["result"]["parts"][0]["text"]
    final_text = final_task_payload["result"]["history"][0]["parts"][0]["text"]

    expected_json = structured.model_dump_json()
    assert message_text == expected_json
    assert final_text == expected_json
