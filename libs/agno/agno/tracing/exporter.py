"""
Custom OpenTelemetry SpanExporter that writes traces to Agno database.
"""

import asyncio
from typing import Sequence, Union

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from agno.db.base import AsyncBaseDb, BaseDb
from agno.tracing.schemas import TraceSpan
from agno.utils.log import logger


class DatabaseSpanExporter(SpanExporter):
    """Custom OpenTelemetry SpanExporter that writes to Agno database"""

    def __init__(self, db: Union[BaseDb, AsyncBaseDb]):
        """
        Initialize the DatabaseSpanExporter.

        Args:
            db: Database instance (sync or async) to store traces
        """
        self.db = db
        self._shutdown = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """
        Export spans to the database.

        Args:
            spans: Sequence of OpenTelemetry ReadableSpan objects

        Returns:
            SpanExportResult indicating success or failure
        """
        if self._shutdown:
            logger.warning("DatabaseSpanExporter is shutdown, cannot export spans")
            return SpanExportResult.FAILURE

        if not spans:
            return SpanExportResult.SUCCESS

        try:
            # Convert OpenTelemetry spans to TraceSpan objects
            trace_spans = []
            for span in spans:
                try:
                    trace_span = TraceSpan.from_otel_span(span)
                    trace_spans.append(trace_span)
                except Exception as e:
                    logger.error(f"Failed to convert span {span.name}: {e}")
                    # Continue processing other spans
                    continue

            if not trace_spans:
                return SpanExportResult.SUCCESS

            # Handle async DB
            if isinstance(self.db, AsyncBaseDb):
                self._export_async(trace_spans)
            else:
                # Synchronous database
                self.db.create_traces_batch(trace_spans)

            return SpanExportResult.SUCCESS
        except Exception as e:
            logger.error(f"Failed to export spans to database: {e}", exc_info=True)
            return SpanExportResult.FAILURE

    def _export_async(self, trace_spans):
        """Handle async database export"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, schedule the coroutine
                asyncio.create_task(self.db.create_traces_batch(trace_spans))
            else:
                # No running loop, run in new loop
                loop.run_until_complete(self.db.create_traces_batch(trace_spans))
        except RuntimeError:
            # No event loop, create new one
            try:
                asyncio.run(self.db.create_traces_batch(trace_spans))
            except Exception as e:
                logger.error(f"Failed to export async traces: {e}", exc_info=True)

    def shutdown(self) -> None:
        """Shutdown the exporter"""
        self._shutdown = True
        logger.debug("DatabaseSpanExporter shutdown")

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """
        Force flush any pending spans.

        Since we write immediately to the database, this is a no-op.

        Args:
            timeout_millis: Timeout in milliseconds

        Returns:
            True if flush was successful
        """
        return True

