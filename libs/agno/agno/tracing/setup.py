"""
Setup helper functions for configuring Agno tracing.
"""

from typing import Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.tracing.exporter import DatabaseSpanExporter
from agno.utils.log import logger

try:
    from openinference.instrumentation.agno import AgnoInstrumentor
    from opentelemetry import trace as trace_api
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    logger.warning(
        "OpenTelemetry packages not installed. "
        "Install with: pip install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno"
    )


def setup_tracing(
    db: Union[BaseDb, AsyncBaseDb],
    use_batch_processor: bool = True,
    max_queue_size: int = 2048,
    max_export_batch_size: int = 512,
    schedule_delay_millis: int = 5000,
) -> None:
    """
    Set up OpenTelemetry tracing with database export for Agno agents.

    This function configures automatic tracing for all Agno agents, teams, and workflows.
    Traces are automatically captured for:
    - Agent runs (agent.run, agent.arun)
    - Model calls (model.response)
    - Tool executions
    - Team coordination
    - Workflow steps

    Args:
        db: Database instance to store traces (sync or async)
        use_batch_processor: If True, use BatchSpanProcessor for better performance
                            If False, use SimpleSpanProcessor (immediate export)
        max_queue_size: Maximum queue size for batch processor
        max_export_batch_size: Maximum batch size for export
        schedule_delay_millis: Delay in milliseconds between batch exports

    Raises:
        ImportError: If OpenTelemetry packages are not installed

    Example:
        ```python
        from agno.db.sqlite import SqliteDb
        from agno.tracing import setup_tracing

        db = SqliteDb(db_file="tmp/traces.db")
        setup_tracing(db=db)

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

    try:
        # Create tracer provider
        tracer_provider = TracerProvider()

        # Create database exporter
        exporter = DatabaseSpanExporter(db=db)

        # Configure span processor
        if use_batch_processor:
            processor = BatchSpanProcessor(
                exporter,
                max_queue_size=max_queue_size,
                max_export_batch_size=max_export_batch_size,
                schedule_delay_millis=schedule_delay_millis,
            )
            logger.info(
                f"Tracing configured with BatchSpanProcessor "
                f"(queue_size={max_queue_size}, batch_size={max_export_batch_size})"
            )
        else:
            processor = SimpleSpanProcessor(exporter)
            logger.info("Tracing configured with SimpleSpanProcessor (immediate export)")

        tracer_provider.add_span_processor(processor)

        # Set the global tracer provider
        trace_api.set_tracer_provider(tracer_provider)

        # Instrument Agno with OpenInference
        AgnoInstrumentor().instrument(tracer_provider=tracer_provider)

        logger.info("Agno tracing successfully set up with database storage")
    except Exception as e:
        logger.error(f"Failed to set up tracing: {e}", exc_info=True)
        raise
