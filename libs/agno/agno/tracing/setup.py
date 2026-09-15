"""
Setup helper functions for configuring Agno tracing.
"""

from typing import List, Optional, Sequence, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.remote.base import RemoteDb
from agno.tracing.exporter import DatabaseSpanExporter
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from openinference.instrumentation.agno import AgnoInstrumentor  # type: ignore
    from opentelemetry import trace as trace_api  # type: ignore
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore
    from opentelemetry.sdk.trace.export import (  # type: ignore
        BatchSpanProcessor,
        SimpleSpanProcessor,
        SpanExporter,
        SpanProcessor,
    )

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False


def _get_attached_exporters(tracer_provider: "TracerProvider") -> List[Optional["SpanExporter"]]:
    """Return the exporters already attached to the given tracer provider.

    Relies on SDK internals, so any failure is treated as "nothing attached".
    """
    try:
        processors = tracer_provider._active_span_processor._span_processors
        return [getattr(processor, "span_exporter", None) for processor in processors]
    except Exception:
        return []


def setup_tracing(
    db: Optional[Union[BaseDb, AsyncBaseDb, RemoteDb]] = None,
    exporters: Optional[Sequence["SpanExporter"]] = None,
    batch_processing: bool = False,
    max_queue_size: int = 2048,
    max_export_batch_size: int = 512,
    schedule_delay_millis: int = 5000,
) -> None:
    """
    Set up OpenTelemetry tracing for Agno agents.

    This function configures automatic tracing for all Agno agents, teams, and workflows.
    Traces are automatically captured for:
    - Agent runs (agent.run, agent.arun)
    - Model calls (model.response)
    - Tool executions
    - Team coordination
    - Workflow steps

    Spans can be exported to the Agno database (pass ``db``), to any external
    OpenTelemetry exporter such as Langfuse or Arize via OTLP (pass ``exporters``),
    or to all of them at once. All exporters are attached to a single tracer
    provider, so every destination receives the same spans with the same trace_id.

    If a global tracer provider is already configured (for example by another
    observability integration), the Agno exporters are attached to it instead of
    replacing it.

    Args:
        db: Database instance to store traces (sync or async)
        exporters: Additional OpenTelemetry span exporters to attach, e.g. an
                   ``OTLPSpanExporter`` pointed at Langfuse or Arize
        batch_processing: If True, use BatchSpanProcessor for better performance
                            If False, use SimpleSpanProcessor (immediate export)
        max_queue_size: Maximum queue size for batch processor
        max_export_batch_size: Maximum batch size for export
        schedule_delay_millis: Delay in milliseconds between batch exports

    Raises:
        ImportError: If OpenTelemetry packages are not installed
        ValueError: If neither db nor exporters are provided

    Example:
        ```python
        from agno.db.sqlite import SqliteDb
        from agno.tracing import setup_tracing

        db = SqliteDb(db_file="tmp/traces.db")

        # Export traces to the Agno database
        setup_tracing(db=db)

        # Export traces to the Agno database and to Langfuse via OTLP
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        setup_tracing(db=db, exporters=[OTLPSpanExporter()])

        # Now all agents will be automatically traced
        agent = Agent(...)
        agent.run("Hello")  # This will be traced automatically
        ```
    """
    if not OPENTELEMETRY_AVAILABLE:
        raise ImportError(
            "OpenTelemetry packages are required for tracing. "
            "Install with: pip install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno"
        )

    if db is None and not exporters:
        raise ValueError("setup_tracing() requires a db, one or more exporters, or both")

    try:
        # Reuse the global tracer provider if one is already configured
        # (handles reload scenarios and third-party integrations set up first)
        current_provider = trace_api.get_tracer_provider()
        if isinstance(current_provider, TracerProvider):
            tracer_provider = current_provider
            set_global_provider = False
            log_debug("Reusing existing global tracer provider")
        else:
            tracer_provider = TracerProvider()
            set_global_provider = True

        attached_exporters = _get_attached_exporters(tracer_provider)

        # Collect the exporters to attach, skipping any already attached
        exporters_to_attach: List[SpanExporter] = []
        if db is not None:
            if any(isinstance(exporter, DatabaseSpanExporter) for exporter in attached_exporters):
                log_debug("DatabaseSpanExporter already attached, skipping")
            else:
                exporters_to_attach.append(DatabaseSpanExporter(db=db))
        for exporter in exporters or []:
            if any(exporter is attached for attached in attached_exporters):
                log_debug(f"Exporter {type(exporter).__name__} already attached, skipping")
            else:
                exporters_to_attach.append(exporter)

        for exporter in exporters_to_attach:
            processor: SpanProcessor
            if batch_processing:
                processor = BatchSpanProcessor(
                    exporter,
                    max_queue_size=max_queue_size,
                    max_export_batch_size=max_export_batch_size,
                    schedule_delay_millis=schedule_delay_millis,
                )
                log_debug(
                    f"Attached {type(exporter).__name__} with BatchSpanProcessor "
                    f"(queue_size={max_queue_size}, batch_size={max_export_batch_size})"
                )
            else:
                processor = SimpleSpanProcessor(exporter)
                log_debug(f"Attached {type(exporter).__name__} with SimpleSpanProcessor")
            tracer_provider.add_span_processor(processor)

        if set_global_provider:
            trace_api.set_tracer_provider(tracer_provider)

        # Instrument Agno with OpenInference
        instrumentor = AgnoInstrumentor()
        if instrumentor.is_instrumented_by_opentelemetry:
            if set_global_provider:
                log_warning(
                    "AgnoInstrumentor is already instrumented with a different tracer provider, "
                    "so the exporters configured by setup_tracing() will not receive spans. "
                    "Remove the manual AgnoInstrumentor().instrument() call and pass your "
                    "exporters to setup_tracing() instead."
                )
        else:
            instrumentor.instrument(tracer_provider=tracer_provider)

        log_info("Agno tracing successfully set up")
    except Exception as e:
        log_error(f"Failed to set up tracing: {str(e)}")
        raise
