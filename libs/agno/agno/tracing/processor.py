"""
Span processor that decides which spans reach Agno's trace store.
"""

from typing import Dict, List, Optional, Tuple

from opentelemetry import trace as trace_api  # type: ignore
from opentelemetry.attributes import BoundedAttributes  # type: ignore
from opentelemetry.context import Context  # type: ignore
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor  # type: ignore

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

    By default outside spans are dropped and each root is forwarded without a parent,
    so the stored trace is rooted at the Agno run. With keep_outside_spans=True they
    are forwarded too and roots keep their parent, so a request and the runs it starts
    are stored as one tree. Outside spans that end before their outermost outside
    ancestor are held back and forwarded right after it, so that ancestor names the
    trace when no run does.

    Positions are forgotten when a span ends, so a span started after its parent
    has ended is classified as if it had no parent.
    """

    def __init__(self, span_processor: SpanProcessor, keep_outside_spans: bool = False):
        self._span_processor = span_processor
        self._keep_outside_spans = keep_outside_spans
        # Positions of started spans that have not ended yet
        self._positions: Dict[_SpanKey, str] = {}
        # Outermost outside ancestor of each open outside span
        self._outside_roots: Dict[_SpanKey, _SpanKey] = {}
        # Ended outside spans waiting for their outermost outside ancestor to end
        self._pending: Dict[_SpanKey, List[ReadableSpan]] = {}

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        parent = trace_api.get_current_span(parent_context).get_span_context()
        parent_key = (parent.trace_id, parent.span_id)
        parent_position = self._positions.get(parent_key) if parent.is_valid else None
        context = span.get_span_context()
        key = (context.trace_id, context.span_id)

        position: Optional[str] = None
        if parent_position in (_ROOT, _INSIDE):
            position = _INSIDE
        elif span.instrumentation_scope is not None and span.instrumentation_scope.name == AGNO_INSTRUMENTATION_SCOPE:
            position = _ROOT
        elif self._keep_outside_spans:
            position = _OUTSIDE
            self._outside_roots[key] = self._outside_roots.get(parent_key, key)

        if position is not None:
            self._positions[key] = position
            self._span_processor.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        context = span.context
        if context is None:
            return
        key = (context.trace_id, context.span_id)
        position = self._positions.pop(key, None)
        if position is None:
            return

        if position == _ROOT:
            self._span_processor.on_end(_as_run_root(span, keep_parent=self._keep_outside_spans))
        elif position == _INSIDE:
            self._span_processor.on_end(span)
        else:
            outside_root = self._outside_roots.pop(key, key)
            if outside_root != key:
                self._pending.setdefault(outside_root, []).append(span)
                return
            self._span_processor.on_end(span)
            for pending_span in self._pending.pop(key, []):
                self._span_processor.on_end(pending_span)

    def shutdown(self) -> None:
        self._span_processor.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._span_processor.force_flush(timeout_millis)


def _as_run_root(span: ReadableSpan, keep_parent: bool) -> ReadableSpan:
    """Copy a finished span with the run root marker, optionally removing its parent."""
    # The copy is built here, so span attribute limits can't evict the marker
    attributes = BoundedAttributes(attributes=span.attributes, immutable=False)
    attributes[AGNO_RUN_ROOT_ATTRIBUTE] = True
    attributes.dropped = span.dropped_attributes
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent if keep_parent else None,
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
