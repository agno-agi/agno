from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agno.tracing import setup as tracing

pytest.importorskip("openinference.instrumentation.agno")


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
        with provider.get_tracer(__name__).start_as_current_span("model", attributes=attributes):
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
    try:
        tracing.setup_tracing(db=MagicMock())
        set_provider.assert_not_called()
        instrumentor.assert_not_called()
    finally:
        provider.shutdown()
