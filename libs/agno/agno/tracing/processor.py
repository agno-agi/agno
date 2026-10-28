"""
Span processor that decides which spans reach Agno's trace store.
"""

import threading
from typing import Dict, List, Optional, Tuple

from opentelemetry import trace as trace_api  # type: ignore
from opentelemetry.attributes import BoundedAttributes  # type: ignore
from opentelemetry.context import Context  # type: ignore
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor  # type: ignore
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator  # type: ignore
from opentelemetry.trace import SpanContext  # type: ignore

from agno.tracing.schemas import AGNO_RUN_ROOT_ATTRIBUTE

# Instrumentation scope of the spans created by openinference-instrumentation-agno
AGNO_INSTRUMENTATION_SCOPE = "openinference.instrumentation.agno"

_ROOT = "root"
_INSIDE = "inside"
_OUTSIDE = "outside"

_SpanKey = Tuple[int, int]


class AgnoSpanFilterProcessor(SpanProcessor):
    """Forward Agno spans, and optionally the application spans around them, to the wrapped processor.

    Once a global tracer provider exists, other libraries can emit spans into it too.
    FastAPI 0.142.0+, for example, traces every request by default, which wraps each
    Agno run in an HTTP request span. Traces are stored with their identity (name,
    run_id, session_id, agent_id) taken from the Agno run, so the processor marks the
    outermost Agno span of each run with the agno.run.root attribute.

    Each span's position is decided when it starts, while its parent is known:
    - root: an Agno span whose parent is missing or outside Agno.
    - inside: any span whose parent is a root or inside span, including user spans
      created inside tools.
    - outside: everything else, e.g. HTTP request spans.

    By default outside spans are dropped, so the stored trace is rooted at the Agno
    run. With keep_outside_spans=True they are forwarded too and roots keep their
    parent, so a request and the runs it starts are stored as one tree. Outside spans that end before their outermost outside
    ancestor are held back and forwarded right after it, so that ancestor names the
    trace when no run does.

    The topmost forwarded span of a tree can have a parent that isn't forwarded: the
    request span around a run, or a client's traceparent header. It is forwarded
    without that parent, so the stored tree has a root. The parent's trace_id can be
    shared by unrelated runs or requests, e.g. a header reused across requests from
    different users, so each such tree is forwarded under a new trace_id of its own
    and is never stored as part of another one.

    Positions are forgotten when a span ends, so a span started after its parent
    has ended is classified as if it had no parent.
    """

    def __init__(self, span_processor: SpanProcessor, keep_outside_spans: bool = False):
        self._span_processor = span_processor
        self._keep_outside_spans = keep_outside_spans
        self._lock = threading.Lock()
        self._id_generator = RandomIdGenerator()
        # Position and tree (its topmost forwarded span) of each started span that has not ended yet
        self._positions: Dict[_SpanKey, Tuple[str, _SpanKey]] = {}
        # Open spans per tree, to know when a tree's state can be dropped
        self._open_spans: Dict[_SpanKey, int] = {}
        # New trace_id for each tree whose topmost span had a parent that isn't forwarded
        self._tree_trace_ids: Dict[_SpanKey, int] = {}
        # Ended outside spans waiting for the top of their tree to end
        self._pending: Dict[_SpanKey, List[ReadableSpan]] = {}

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        parent = trace_api.get_current_span(parent_context).get_span_context()
        context = span.get_span_context()
        key = (context.trace_id, context.span_id)
        is_agno = (
            span.instrumentation_scope is not None and span.instrumentation_scope.name == AGNO_INSTRUMENTATION_SCOPE
        )

        with self._lock:
            parent_entry = self._positions.get((parent.trace_id, parent.span_id)) if parent.is_valid else None
            if parent_entry is not None:
                parent_position, tree_key = parent_entry
                if parent_position in (_ROOT, _INSIDE):
                    position = _INSIDE
                else:
                    position = _ROOT if is_agno else _OUTSIDE
            else:
                if is_agno:
                    position = _ROOT
                elif self._keep_outside_spans:
                    position = _OUTSIDE
                else:
                    return
                tree_key = key
                if parent.is_valid:
                    self._tree_trace_ids[key] = self._id_generator.generate_trace_id()
            self._positions[key] = (position, tree_key)
            self._open_spans[tree_key] = self._open_spans.get(tree_key, 0) + 1

        self._span_processor.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        context = span.context
        if context is None:
            return
        key = (context.trace_id, context.span_id)

        with self._lock:
            entry = self._positions.pop(key, None)
            if entry is None:
                return
            position, tree_key = entry
            trace_id = self._tree_trace_ids.get(tree_key)
            self._open_spans[tree_key] -= 1
            if self._open_spans[tree_key] == 0:
                del self._open_spans[tree_key]
                self._tree_trace_ids.pop(tree_key, None)

        # The top of a tree loses its parent, which isn't forwarded (or is a client's traceparent)
        is_top = tree_key == key
        if position == _ROOT or (is_top and span.parent is not None) or trace_id is not None:
            span = _rewrite(
                span,
                trace_id=trace_id,
                drop_parent=is_top,
                mark_run_root=position == _ROOT,
            )

        if position == _OUTSIDE:
            with self._lock:
                if tree_key != key:
                    self._pending.setdefault(tree_key, []).append(span)
                    return
                pending = self._pending.pop(key, [])
            self._span_processor.on_end(span)
            for pending_span in pending:
                self._span_processor.on_end(pending_span)
            return

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


def _rewrite(
    span: ReadableSpan,
    trace_id: Optional[int],
    drop_parent: bool = False,
    mark_run_root: bool = False,
) -> ReadableSpan:
    """Copy a finished span, optionally moving it to another trace, removing its parent or marking it as a run root."""
    attributes = span.attributes
    if mark_run_root:
        # The copy is built here, so span attribute limits can't evict the marker
        attributes = BoundedAttributes(attributes=span.attributes, immutable=False)
        attributes[AGNO_RUN_ROOT_ATTRIBUTE] = True
        attributes.dropped = span.dropped_attributes
    return ReadableSpan(
        name=span.name,
        context=_with_trace_id(span.context, trace_id) if span.context else None,
        parent=None if drop_parent or span.parent is None else _with_trace_id(span.parent, trace_id),
        resource=span.resource,
        attributes=attributes,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )
