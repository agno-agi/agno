"""
End-to-end test: an instrumented agent run captures the OTel trace_id on its
RunOutput and streamed events, matching the trace_id of the exported spans.

Runs the full run() path against a mock model (no network) with
AgnoInstrumentor active, the same way setup_tracing() instruments Agno.
"""

from typing import Any, AsyncIterator, Iterator

import pytest
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse

TRACE_ID_HEX_LENGTH = 32


class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="ok",
            role="assistant",
            response_usage=MessageMetrics(),
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

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


@pytest.fixture
def span_exporter():
    """Instrument Agno with a private tracer provider exporting to memory."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    instrumentor = AgnoInstrumentor()
    if instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.uninstrument()
    instrumentor.instrument(tracer_provider=provider)
    yield exporter
    instrumentor.uninstrument()


def test_run_output_carries_trace_id_of_exported_spans(span_exporter):
    agent = Agent(model=MockModel(), name="Traced Agent")

    response = agent.run("hello")

    assert response.trace_id is not None
    assert len(response.trace_id) == TRACE_ID_HEX_LENGTH

    exported_trace_ids = {format(span.context.trace_id, "032x") for span in span_exporter.get_finished_spans()}
    assert exported_trace_ids == {response.trace_id}


def test_streamed_events_carry_trace_id(span_exporter):
    agent = Agent(model=MockModel(), name="Traced Agent")

    events = list(agent.run("hello", stream=True))

    assert len(events) > 0
    trace_ids = {event.trace_id for event in events}
    assert len(trace_ids) == 1
    trace_id = trace_ids.pop()
    assert trace_id is not None
    assert len(trace_id) == TRACE_ID_HEX_LENGTH


@pytest.mark.asyncio
async def test_async_run_output_carries_trace_id(span_exporter):
    agent = Agent(model=MockModel(), name="Traced Agent")

    response = await agent.arun("hello")

    assert response.trace_id is not None
    assert len(response.trace_id) == TRACE_ID_HEX_LENGTH


def test_run_output_trace_id_is_none_without_instrumentation():
    agent = Agent(model=MockModel(), name="Untraced Agent")

    response = agent.run("hello")

    assert response.trace_id is None
