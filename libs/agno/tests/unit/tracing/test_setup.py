from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tracing import setup as tracing
from agno.tracing.processor import AGNO_INSTRUMENTATION_SCOPE

pytest.importorskip("openinference.instrumentation.agno")


class MockModel(Model):
    """Offline model returning a canned response."""

    def __init__(self):
        super().__init__(id="mock", name="mock", provider="mock")

    def invoke(self, *args, **kwargs):
        return ModelResponse(content="ok")

    async def ainvoke(self, *args, **kwargs):
        return ModelResponse(content="ok")

    def invoke_stream(self, *args, **kwargs):
        yield ModelResponse(content="ok")

    async def ainvoke_stream(self, *args, **kwargs):
        yield ModelResponse(content="ok")

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.mark.parametrize("batch_processing", [False, True])
@pytest.mark.parametrize(
    "global_limit, span_limit, expected_count",
    [(None, None, 300), ("64", None, 64), ("64", "96", 96), (None, "0", 0)],
)
def test_setup_retains_llm_attributes_and_respects_explicit_limits(
    monkeypatch, batch_processing, global_limit, span_limit, expected_count
):
    for key, value in [("OTEL_ATTRIBUTE_COUNT_LIMIT", global_limit), ("OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT", span_limit)]:
        monkeypatch.delenv(key, raising=False)
        if value is not None:
            monkeypatch.setenv(key, value)

    exporter = InMemorySpanExporter()
    set_provider = MagicMock()
    instrumentor = MagicMock()
    monkeypatch.setattr(tracing.trace_api, "get_tracer_provider", lambda: None)
    monkeypatch.setattr(tracing.trace_api, "set_tracer_provider", set_provider)
    monkeypatch.setattr(tracing, "DatabaseSpanExporter", lambda db: exporter)
    monkeypatch.setattr(tracing, "AgnoInstrumentor", lambda: instrumentor)

    tracing.setup_tracing(db=MagicMock(), batch_processing=batch_processing)
    provider = set_provider.call_args.args[0]
    try:
        instrumentor.instrument.assert_called_once_with(tracer_provider=provider)
        attributes = {f"llm.input_messages.{i}.message.content": f"Message {i}" for i in range(300)}
        with provider.get_tracer(AGNO_INSTRUMENTATION_SCOPE).start_as_current_span("model", attributes=attributes):
            pass
        assert provider.force_flush()
        (span,) = exporter.get_finished_spans()
        assert len(span.attributes) == expected_count
        assert span.dropped_attributes == 300 - expected_count
        if expected_count == 300:
            assert dict(span.attributes) == attributes
    finally:
        provider.shutdown()


def test_setup_preserves_existing_otel_provider(monkeypatch):
    provider = TracerProvider()
    set_provider = MagicMock()
    instrumentor = MagicMock()
    monkeypatch.setattr(tracing.trace_api, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(tracing.trace_api, "set_tracer_provider", set_provider)
    monkeypatch.setattr(tracing, "AgnoInstrumentor", instrumentor)
    monkeypatch.setattr(tracing, "_agno_tracer_provider", None)
    try:
        tracing.setup_tracing(db=MagicMock())
        set_provider.assert_not_called()
        instrumentor.assert_not_called()
        assert tracing.is_agno_tracing_active() is False
    finally:
        provider.shutdown()


def test_agno_tracing_is_active_once_its_provider_is_global(monkeypatch):
    global_provider = {}
    monkeypatch.setattr(tracing.trace_api, "get_tracer_provider", lambda: global_provider.get("provider"))
    monkeypatch.setattr(tracing.trace_api, "set_tracer_provider", lambda p: global_provider.update(provider=p))
    monkeypatch.setattr(tracing, "AgnoInstrumentor", MagicMock())
    monkeypatch.setattr(tracing, "_agno_tracer_provider", None)

    assert tracing.is_agno_tracing_active() is False
    tracing.setup_tracing(db=MagicMock())
    try:
        assert tracing.is_agno_tracing_active() is True
    finally:
        global_provider["provider"].shutdown()


def test_setup_stores_spans_from_the_real_instrumentor(monkeypatch):
    exporter = InMemorySpanExporter()
    set_provider = MagicMock()
    monkeypatch.setattr(tracing.trace_api, "get_tracer_provider", lambda: None)
    monkeypatch.setattr(tracing.trace_api, "set_tracer_provider", set_provider)
    monkeypatch.setattr(tracing, "DatabaseSpanExporter", lambda db: exporter)

    tracing.setup_tracing(db=MagicMock(), batch_processing=False)
    provider = set_provider.call_args.args[0]
    try:
        Agent(model=MockModel(), telemetry=False).run("Say hi")
        # The filter keeps spans by instrumentation scope, so a rename in openinference would drop every span
        assert "Agent.run" in [span.name for span in exporter.get_finished_spans()]
    finally:
        tracing.AgnoInstrumentor().uninstrument()
        provider.shutdown()
