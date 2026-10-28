"""
Span processor that keeps only Agno runs when other libraries also emit spans.
"""

from typing import Dict, Optional, Tuple

from opentelemetry import trace as trace_api  # type: ignore
from opentelemetry.context import Context  # type: ignore
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor  # type: ignore

# Instrumentation scope of the spans created by openinference-instrumentation-agno
AGNO_INSTRUMENTATION_SCOPE = "openinference.instrumentation.agno"

_ROOT = "root"
_INSIDE = "inside"


class AgnoSpanFilterProcessor(SpanProcessor):
    """Forward only Agno spans and their descendants to the wrapped processor.

    Once a global tracer provider exists, other libraries can emit spans into it too.
    FastAPI 0.142.0+, for example, traces every request by default, which wraps each
    Agno run in an HTTP request span. Traces are stored by their root span, so a
    foreign root would hide the run's name, run_id, session_id and agent_id.

    Each span's position is decided when it starts, while its parent is known:
    - root: an Agno span whose parent is missing or outside Agno. It is forwarded
      without a parent, so the stored trace is rooted at the Agno run.
    - inside: any span whose parent is a root or inside span, including user spans
      created inside tools.
    - outside: everything else, e.g. HTTP request spans. These are dropped.

    Positions are forgotten when a span ends, so a span started after its parent
    has ended is classified as if it had no parent.
    """

    def __init__(self, span_processor: SpanProcessor):
        self._span_processor = span_processor
        # Positions of started spans that have not ended yet, keyed by (trace_id, span_id)
        self._positions: Dict[Tuple[int, int], str] = {}

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        parent = trace_api.get_current_span(parent_context).get_span_context()
        parent_position = self._positions.get((parent.trace_id, parent.span_id)) if parent.is_valid else None

        position: Optional[str] = None
        if parent_position is not None:
            position = _INSIDE
        elif span.instrumentation_scope is not None and span.instrumentation_scope.name == AGNO_INSTRUMENTATION_SCOPE:
            position = _ROOT

        if position is not None:
            context = span.get_span_context()
            self._positions[(context.trace_id, context.span_id)] = position
            self._span_processor.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        context = span.context
        position = self._positions.pop((context.trace_id, context.span_id), None) if context else None
        if position is None:
            return
        if position == _ROOT and span.parent is not None:
            span = _without_parent(span)
        self._span_processor.on_end(span)

    def shutdown(self) -> None:
        self._span_processor.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._span_processor.force_flush(timeout_millis)


def _without_parent(span: ReadableSpan) -> ReadableSpan:
    """Copy a finished span with its parent removed."""
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=None,
        resource=span.resource,
        attributes=span.attributes,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )
