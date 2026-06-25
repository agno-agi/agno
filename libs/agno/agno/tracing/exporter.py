"""
Custom OpenTelemetry SpanExporter that writes traces to Agno database.
"""

import asyncio
from collections import defaultdict
from typing import Dict, List, Sequence, Set, Union

from opentelemetry.sdk.trace import ReadableSpan  # type: ignore
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult  # type: ignore

from agno.db.base import AsyncBaseDb, BaseDb
from agno.remote.base import RemoteDb
from agno.tracing.schemas import Span, create_trace_from_spans
from agno.utils.log import log_debug, log_error, log_warning


class DatabaseSpanExporter(SpanExporter):
    """Custom OpenTelemetry SpanExporter that writes to Agno database"""

    def __init__(self, db: Union[BaseDb, AsyncBaseDb, RemoteDb]):
        """
        Initialize the DatabaseSpanExporter.

        Args:
            db: Database instance (sync or async) to store traces
        """
        self.db = db
        self._shutdown = False
        # Strong references to in-flight export tasks. asyncio only keeps a weak
        # reference to a task, so without this the task could be garbage-collected
        # mid-run and silently drop traces.
        self._background_tasks: Set[asyncio.Task] = set()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """
        Export spans to the database.

        This method:
        1. Converts OpenTelemetry spans to Span objects
        2. Groups spans by trace_id
        3. Creates Trace records (one per trace_id)
        4. Creates Span records (multiple per trace_id)

        Args:
            spans: Sequence of OpenTelemetry ReadableSpan objects

        Returns:
            SpanExportResult indicating success or failure
        """
        if self._shutdown:
            log_warning("DatabaseSpanExporter is shutdown, cannot export spans")
            return SpanExportResult.FAILURE

        if not spans:
            return SpanExportResult.SUCCESS

        try:
            # Convert OpenTelemetry spans to Span objects
            converted_spans: List[Span] = []
            for span in spans:
                try:
                    converted_span = Span.from_otel_span(span)
                    converted_spans.append(converted_span)
                except Exception as e:
                    log_error(f"Failed to convert span {span.name}: {str(e)}")
                    # Continue processing other spans
                    continue

            if not converted_spans:
                return SpanExportResult.SUCCESS

            # Group spans by trace_id
            spans_by_trace: Dict[str, List[Span]] = defaultdict(list)
            for converted_span in converted_spans:
                spans_by_trace[converted_span.trace_id].append(converted_span)

            # Handle async DB
            if isinstance(self.db, RemoteDb):
                # Skipping remote database because it handles its own tracing
                pass
            elif isinstance(self.db, AsyncBaseDb):
                self._export_async(spans_by_trace)
            else:
                # Synchronous database
                self._export_sync(spans_by_trace)

            return SpanExportResult.SUCCESS
        except Exception as e:
            log_error(f"Failed to export spans to database: {str(e)}")
            return SpanExportResult.FAILURE

    def _export_sync(self, spans_by_trace: Dict[str, List[Span]]) -> None:
        """Export traces and spans to synchronous database"""
        try:
            # Create trace and span records for each trace
            for trace_id, spans in spans_by_trace.items():
                # Create trace record (aggregate of all spans)
                trace = create_trace_from_spans(spans)
                if trace:
                    self.db.upsert_trace(trace)  # type: ignore

                # Create span records
                self.db.create_spans(spans)  # type: ignore

        except Exception as e:
            log_error(f"Failed to export sync traces: {str(e)}")
            raise

    def _export_async(self, spans_by_trace: Dict[str, List[Span]]) -> None:
        """Handle async database export"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop, run the export in a new one
            try:
                asyncio.run(self._do_async_export(spans_by_trace))
            except Exception as e:
                log_error(f"Failed to export async traces: {str(e)}")
            return

        # We're in an async context, schedule the coroutine. Keep a strong
        # reference to the task and drop it on completion so it isn't garbage
        # collected before it finishes (which would silently drop the traces).
        task = loop.create_task(self._do_async_export(spans_by_trace))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _do_async_export(self, spans_by_trace: Dict[str, List[Span]]) -> None:
        """Actually perform the async export"""
        try:
            # Create trace and span records for each trace
            for trace_id, spans in spans_by_trace.items():
                # Create trace record (aggregate of all spans)
                trace = create_trace_from_spans(spans)
                if trace:
                    create_trace_result = self.db.upsert_trace(trace)  # type: ignore
                    if create_trace_result is not None:
                        await create_trace_result

                # Create span records
                create_spans_result = self.db.create_spans(spans)  # type: ignore
                if create_spans_result is not None:
                    await create_spans_result

        except Exception as e:
            log_error(f"Failed to do async export: {str(e)}")
            raise

    def shutdown(self) -> None:
        """Shutdown the exporter"""
        self._shutdown = True
        log_debug("DatabaseSpanExporter shutdown")

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
