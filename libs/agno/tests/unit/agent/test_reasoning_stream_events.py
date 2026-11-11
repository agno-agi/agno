"""Unit tests verifying that reasoning content deltas and events are forwarded
in both sync and async agent streaming, including AgentOS SSE formatting.
"""

from typing import AsyncIterator, Iterator, List, Optional

import pytest

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import (
    ModelRequestCompletedEvent,
    ReasoningContentDeltaEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunEvent,
)


class MockReasoningModel(Model):
    """Offline mock model that streams reasoning chunks followed by content chunks."""

    def __init__(self, reasoning_chunks: Optional[List[str]] = None, content_chunks: Optional[List[str]] = None):
        super().__init__(id="mock-reasoning-model", name="mock-reasoning-model", provider="mock")
        self.instructions = None
        self.reasoning_chunks = (
            reasoning_chunks if reasoning_chunks is not None else ["Let me think about this.", " It makes sense."]
        )
        self.content_chunks = (
            content_chunks if content_chunks is not None else ["Here is the answer.", " Hope this helps!"]
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response: object, **kwargs) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response_delta: object) -> ModelResponse:
        return ModelResponse()

    def _build_stream_responses(self) -> List[ModelResponse]:
        responses = []
        for rc in self.reasoning_chunks:
            responses.append(ModelResponse(reasoning_content=rc))
        for i, cc in enumerate(self.content_chunks):
            # Include metrics on the last chunk
            if i == len(self.content_chunks) - 1:
                responses.append(
                    ModelResponse(
                        content=cc,
                        response_usage=MessageMetrics(
                            input_tokens=10,
                            output_tokens=15,
                            reasoning_tokens=25,
                            total_tokens=50,
                        ),
                    )
                )
            else:
                responses.append(ModelResponse(content=cc))

        if not self.content_chunks and self.reasoning_chunks:
            # If there are only reasoning chunks, attach metrics to the last reasoning chunk
            responses[-1].response_usage = MessageMetrics(
                input_tokens=10,
                output_tokens=15,
                reasoning_tokens=25,
                total_tokens=50,
            )

        return responses

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(
            content="".join(self.content_chunks),
            reasoning_content="".join(self.reasoning_chunks),
            response_usage=MessageMetrics(reasoning_tokens=25, total_tokens=50),
        )

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield from self._build_stream_responses()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for resp in self._build_stream_responses():
            yield resp


def test_sync_streaming_emits_reasoning_events():
    """Verify sync agent.run(stream=True, stream_events=True) emits reasoning lifecycle events."""
    model = MockReasoningModel()
    agent = Agent(model=model)

    events = list(agent.run("Hello", stream=True, stream_events=True))

    event_types = [e.event for e in events]
    assert RunEvent.reasoning_started in event_types
    assert RunEvent.reasoning_content_delta in event_types
    assert RunEvent.reasoning_completed in event_types
    assert RunEvent.run_content in event_types
    assert RunEvent.model_request_completed in event_types
    assert RunEvent.run_completed in event_types

    # Verify order of events: started -> deltas -> completed -> content
    started_idx = event_types.index(RunEvent.reasoning_started)
    first_delta_idx = event_types.index(RunEvent.reasoning_content_delta)
    completed_idx = event_types.index(RunEvent.reasoning_completed)
    first_content_idx = event_types.index(RunEvent.run_content)

    assert started_idx < first_delta_idx < completed_idx <= first_content_idx

    # Verify reasoning delta payloads
    deltas = [e.reasoning_content for e in events if isinstance(e, ReasoningContentDeltaEvent)]
    assert deltas == ["Let me think about this.", " It makes sense."]

    # Verify no empty/null RunContent events during reasoning
    run_content_events = [e for e in events if isinstance(e, RunContentEvent)]
    for rce in run_content_events:
        assert rce.content is not None
        assert rce.content in model.content_chunks

    # Verify model request completed event carries reasoning tokens
    model_request_completed = next(
        e for e in events if isinstance(e, ModelRequestCompletedEvent) and e.reasoning_tokens is not None
    )
    assert model_request_completed.reasoning_tokens == 25

    # Verify final completed event has accumulated content and reasoning
    completed_event = next(e for e in events if isinstance(e, RunCompletedEvent))
    assert completed_event.reasoning_content == "Let me think about this. It makes sense."
    assert completed_event.content == "Here is the answer. Hope this helps!"


@pytest.mark.asyncio
async def test_async_streaming_emits_reasoning_events():
    """Verify async agent.arun(stream=True, stream_events=True) emits reasoning lifecycle events."""
    model = MockReasoningModel()
    agent = Agent(model=model)

    events = []
    async for event in agent.arun("Hello", stream=True, stream_events=True):
        events.append(event)

    event_types = [e.event for e in events]
    assert RunEvent.reasoning_started in event_types
    assert RunEvent.reasoning_content_delta in event_types
    assert RunEvent.reasoning_completed in event_types
    assert RunEvent.run_content in event_types

    deltas = [e.reasoning_content for e in events if isinstance(e, ReasoningContentDeltaEvent)]
    assert deltas == ["Let me think about this.", " It makes sense."]

    final_event = next(e for e in events if isinstance(e, RunCompletedEvent))
    assert final_event.reasoning_content == "Let me think about this. It makes sense."


@pytest.mark.asyncio
async def test_agentos_sse_serialization_of_reasoning_events():
    """Verify that events emitted from agent streaming serialize to standard SSE events for AgentOS clients."""
    model = MockReasoningModel()
    agent = Agent(model=model)

    events = []
    async for event in agent.arun("Hello", stream=True, stream_events=True):
        events.append(event)

    sse_lines: List[str] = []
    for event in events:
        event_type = event.event or "message"
        clean_json = event.to_json(separators=(",", ":"), indent=None)
        sse_lines.append(f"event: {event_type}\ndata: {clean_json}\n\n")

    full_stream = "".join(sse_lines)

    assert "event: ReasoningStarted" in full_stream
    assert "event: ReasoningContentDelta" in full_stream
    assert "event: ReasoningCompleted" in full_stream
    assert "event: RunContent" in full_stream
    assert "event: ModelRequestCompleted" in full_stream
    assert "event: RunCompleted" in full_stream

    assert "Let me think about this." in full_stream
    assert "It makes sense." in full_stream
    assert '"reasoning_tokens":25' in full_stream


def test_reasoning_only_stream_completes_reasoning():
    """Verify that if model response has reasoning but no content, ReasoningCompleted is emitted at stream end."""
    model = MockReasoningModel(reasoning_chunks=["Thinking only."], content_chunks=[])
    agent = Agent(model=model)

    events = list(agent.run("Hello", stream=True, stream_events=True))
    event_types = [e.event for e in events]

    assert RunEvent.reasoning_started in event_types
    assert RunEvent.reasoning_content_delta in event_types
    assert RunEvent.reasoning_completed in event_types
    assert RunEvent.run_content not in event_types


def test_sync_streaming_without_stream_events_backward_compatible():
    """Verify stream=True, stream_events=False preserves RunContentEvent with reasoning_content."""
    model = MockReasoningModel()
    agent = Agent(model=model)

    chunks = list(agent.run("Hello", stream=True, stream_events=False))
    reasoning_chunks = [c.reasoning_content for c in chunks if c.reasoning_content]
    assert reasoning_chunks == ["Let me think about this.", " It makes sense."]


@pytest.mark.asyncio
async def test_agentos_router_streamer_integration():
    """Optional integration test with AgentOS router if fastapi is available."""
    pytest.importorskip("fastapi")
    from agno.os.routers.agents.router import agent_response_streamer

    model = MockReasoningModel()
    agent = Agent(model=model)

    sse_chunks: List[str] = []
    async for sse in agent_response_streamer(agent, message="Hello"):
        sse_chunks.append(sse)

    full_stream = "".join(sse_chunks)
    assert "event: ReasoningContentDelta" in full_stream
    assert "Let me think about this." in full_stream
