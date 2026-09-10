"""
Unit tests for agno.tracing.setup.setup_tracing.

setup_tracing() mutates process-global state: the OTel global tracer provider
(set-once by design) and the AgnoInstrumentor singleton. The autouse fixture
below resets both around every test so cases stay isolated.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace as trace_api
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.util._once import Once

from agno.tracing.exporter import DatabaseSpanExporter
from agno.tracing.setup import setup_tracing


@pytest.fixture(autouse=True)
def reset_otel_global_state():
    """Reset the OTel global tracer provider and the AgnoInstrumentor singleton."""

    def _reset():
        trace_api._TRACER_PROVIDER = None
        trace_api._TRACER_PROVIDER_SET_ONCE = Once()
        instrumentor = AgnoInstrumentor()
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()

    _reset()
    yield
    _reset()


def _attached_processors(provider: Any):
    return provider._active_span_processor._span_processors


def _attached_exporters(provider: Any):
    return [getattr(p, "span_exporter", None) for p in _attached_processors(provider)]


def test_requires_db_or_exporters():
    with pytest.raises(ValueError):
        setup_tracing()


def test_db_only_sets_global_provider_with_database_exporter():
    setup_tracing(db=MagicMock())

    provider = trace_api.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporters = _attached_exporters(provider)
    assert len(exporters) == 1
    assert isinstance(exporters[0], DatabaseSpanExporter)
    assert AgnoInstrumentor().is_instrumented_by_opentelemetry


def test_exporters_only_does_not_require_db():
    exporter = InMemorySpanExporter()

    setup_tracing(exporters=[exporter])

    provider = trace_api.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    assert _attached_exporters(provider) == [exporter]


def test_db_and_exporters_attach_to_the_same_provider():
    exporter = InMemorySpanExporter()

    setup_tracing(db=MagicMock(), exporters=[exporter])

    provider = trace_api.get_tracer_provider()
    exporter_types = [type(e) for e in _attached_exporters(provider)]
    assert exporter_types == [DatabaseSpanExporter, InMemorySpanExporter]


def test_all_exporters_receive_the_same_trace_id():
    exporter_a = InMemorySpanExporter()
    exporter_b = InMemorySpanExporter()

    setup_tracing(exporters=[exporter_a, exporter_b])

    tracer = trace_api.get_tracer("test")
    with tracer.start_as_current_span("run") as span:
        trace_id = span.get_span_context().trace_id

    spans_a = exporter_a.get_finished_spans()
    spans_b = exporter_b.get_finished_spans()
    assert len(spans_a) == len(spans_b) == 1
    assert spans_a[0].context.trace_id == trace_id
    assert spans_b[0].context.trace_id == trace_id


def test_reuses_existing_global_provider():
    pre_existing_exporter = InMemorySpanExporter()
    pre_existing_provider = TracerProvider()
    pre_existing_provider.add_span_processor(SimpleSpanProcessor(pre_existing_exporter))
    trace_api.set_tracer_provider(pre_existing_provider)

    setup_tracing(db=MagicMock())

    assert trace_api.get_tracer_provider() is pre_existing_provider
    exporter_types = [type(e) for e in _attached_exporters(pre_existing_provider)]
    assert exporter_types == [InMemorySpanExporter, DatabaseSpanExporter]
    assert AgnoInstrumentor().is_instrumented_by_opentelemetry


def test_repeated_calls_do_not_duplicate_processors():
    exporter = InMemorySpanExporter()

    setup_tracing(db=MagicMock(), exporters=[exporter])
    provider = trace_api.get_tracer_provider()
    processor_count = len(_attached_processors(provider))

    setup_tracing(db=MagicMock(), exporters=[exporter])

    assert len(_attached_processors(provider)) == processor_count


def test_distinct_exporter_instances_are_both_attached():
    exporter_a = InMemorySpanExporter()
    exporter_b = InMemorySpanExporter()

    setup_tracing(exporters=[exporter_a])
    setup_tracing(exporters=[exporter_b])

    provider = trace_api.get_tracer_provider()
    assert _attached_exporters(provider) == [exporter_a, exporter_b]


def test_batch_processing_uses_batch_processor():
    setup_tracing(db=MagicMock(), batch_processing=True)

    provider = trace_api.get_tracer_provider()
    processors = _attached_processors(provider)
    assert len(processors) == 1
    assert isinstance(processors[0], BatchSpanProcessor)


def test_simple_processor_by_default():
    setup_tracing(db=MagicMock())

    provider = trace_api.get_tracer_provider()
    processors = _attached_processors(provider)
    assert len(processors) == 1
    assert isinstance(processors[0], SimpleSpanProcessor)


def test_warns_when_instrumentor_already_bound_to_another_provider():
    foreign_provider = TracerProvider()
    AgnoInstrumentor().instrument(tracer_provider=foreign_provider)

    with patch("agno.tracing.setup.log_warning") as mock_log_warning:
        setup_tracing(db=MagicMock())

    assert mock_log_warning.call_count == 1
    assert "already instrumented" in mock_log_warning.call_args[0][0]
