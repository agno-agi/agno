"""
Span processor that keeps only Agno runs when other libraries also emit spans.
"""

import threading
from typing import Dict, Optional, Tuple

from opentelemetry import trace as trace_api  # type: ignore
from opentelemetry.context import Context  # type: ignore
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor  # type: ignore
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator  # type: ignore
from opentelemetry.trace import SpanContext  # type: ignore

# Instrumentation scope of the spans created by openinference-instrumentation-agno
AGNO_INSTRUMENTATION_SCOPE = "openinference.instrumentation.agno"

_ROOT = "root"
_INSIDE = "inside"

_SpanKey = Tuple[int, int]


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

    A root with a parent outside Agno shares that parent's trace_id, which can be
    shared by unrelated runs: a client's traceparent header reused across requests,
    or two runs in one request. Each such run is forwarded under a new trace_id of
    its own, so runs are never stored as one trace.

    Positions are forgotten when a span ends, so a span started after its parent
    has ended is classified as if it had no parent.
    """

    def __init__(self, span_processor: SpanProcessor):
        self._span_processor = span_processor
        self._lock = threading.Lock()
        self._id_generator = RandomIdGenerator()
        # Position and run root of each started span that has not ended yet
        self._positions: Dict[_SpanKey, Tuple[str, _SpanKey]] = {}
        # Open spans per run root, to know when a run's state can be dropped
        self._open_spans: Dict[_SpanKey, int] = {}
        # New trace_id for each run whose root had a parent outside Agno
        self._run_trace_ids: Dict[_SpanKey, int] = {}

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        parent = trace_api.get_current_span(parent_context).get_span_context()
        context = span.get_span_context()
        key = (context.trace_id, context.span_id)

        with self._lock:
            parent_entry = self._positions.get((parent.trace_id, parent.span_id)) if parent.is_valid else None
            if parent_entry is not None:
                position, run_key = _INSIDE, parent_entry[1]
            elif (
                span.instrumentation_scope is not None and span.instrumentation_scope.name == AGNO_INSTRUMENTATION_SCOPE
            ):
                position, run_key = _ROOT, key
                if parent.is_valid:
                    self._run_trace_ids[key] = self._id_generator.generate_trace_id()
            else:
                return
            self._positions[key] = (position, run_key)
            self._open_spans[run_key] = self._open_spans.get(run_key, 0) + 1

        self._span_processor.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        context = span.context
        if context is None:
            return

        with self._lock:
            entry = self._positions.pop((context.trace_id, context.span_id), None)
            if entry is None:
                return
            position, run_key = entry
            trace_id = self._run_trace_ids.get(run_key)
            self._open_spans[run_key] -= 1
            if self._open_spans[run_key] == 0:
                del self._open_spans[run_key]
                self._run_trace_ids.pop(run_key, None)

        drop_parent = position == _ROOT and span.parent is not None
        if drop_parent or trace_id is not None:
            span = _rewrite(span, trace_id=trace_id, drop_parent=drop_parent)
        self._span_processor.on_end(span)

    def shutdown(self) -> None:
        self._span_processor.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._span_processor.force_flush(timeout_millis)


def _with_trace_id(context: SpanContext, trace_id: Optional[int]) -> SpanContext:
    if trace_id is None:
        return context
    return SpanContext(
        trace_id=trace_id,
        span_id=context.span_id,
        is_remote=False,
        trace_flags=context.trace_flags,
        trace_state=context.trace_state,
    )


def _rewrite(span: ReadableSpan, trace_id: Optional[int], drop_parent: bool) -> ReadableSpan:
    """Copy a finished span, optionally moving it to another trace and removing its parent."""
    return ReadableSpan(
        name=span.name,
        context=_with_trace_id(span.context, trace_id) if span.context else None,
        parent=None if drop_parent or span.parent is None else _with_trace_id(span.parent, trace_id),
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
