"""
Trace data models for Agno tracing.
"""

from dataclasses import asdict, dataclass
from time import time
from typing import Any, Dict, List, Optional

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind, StatusCode


@dataclass
class Trace:
    """Represents a complete trace (one record per trace_id)"""

    trace_id: str
    name: str  # Name from root span
    status: str  # Overall status: OK, ERROR, UNSET
    start_time_ns: int
    end_time_ns: int
    duration_ms: int
    total_spans: int
    error_count: int

    # Context from root span
    run_id: Optional[str]
    session_id: Optional[str]
    user_id: Optional[str]
    agent_id: Optional[str]

    created_at: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert Trace to dictionary for database storage"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trace":
        """Create Trace from dictionary"""
        return cls(
            trace_id=data["trace_id"],
            name=data["name"],
            status=data["status"],
            start_time_ns=data["start_time_ns"],
            end_time_ns=data["end_time_ns"],
            duration_ms=data["duration_ms"],
            total_spans=data["total_spans"],
            error_count=data["error_count"],
            run_id=data.get("run_id"),
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            agent_id=data.get("agent_id"),
            created_at=data["created_at"],
        )


@dataclass
class Span:
    """Represents a single span within a trace"""

    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    name: str
    span_kind: str
    status_code: str
    status_message: Optional[str]
    start_time_ns: int
    end_time_ns: int
    duration_ms: int
    attributes: Dict[str, Any]
    events: List[Dict[str, Any]]
    created_at: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert Span to dictionary for database storage"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Span":
        """Create Span from dictionary"""
        return cls(
            span_id=data["span_id"],
            trace_id=data["trace_id"],
            parent_span_id=data.get("parent_span_id"),
            name=data["name"],
            span_kind=data["span_kind"],
            status_code=data["status_code"],
            status_message=data.get("status_message"),
            start_time_ns=data["start_time_ns"],
            end_time_ns=data["end_time_ns"],
            duration_ms=data["duration_ms"],
            attributes=data.get("attributes", {}),
            events=data.get("events", []),
            created_at=data["created_at"],
        )

    @classmethod
    def from_otel_span(cls, otel_span: ReadableSpan) -> "Span":
        """Convert OpenTelemetry ReadableSpan to Span"""
        # Extract span context
        span_context = otel_span.context
        trace_id = format(span_context.trace_id, "032x") if span_context else "0" * 32
        span_id = format(span_context.span_id, "016x") if span_context else "0" * 16

        # Extract parent span ID if exists
        parent_span_id = None
        if otel_span.parent and otel_span.parent.span_id:
            parent_span_id = format(otel_span.parent.span_id, "016x")

        # Extract span kind
        span_kind_map = {
            SpanKind.INTERNAL: "INTERNAL",
            SpanKind.SERVER: "SERVER",
            SpanKind.CLIENT: "CLIENT",
            SpanKind.PRODUCER: "PRODUCER",
            SpanKind.CONSUMER: "CONSUMER",
        }
        span_kind = span_kind_map.get(otel_span.kind, "INTERNAL")

        # Extract status
        status_code_map = {
            StatusCode.UNSET: "UNSET",
            StatusCode.OK: "OK",
            StatusCode.ERROR: "ERROR",
        }
        status_code = status_code_map.get(otel_span.status.status_code, "UNSET")
        status_message = otel_span.status.description

        # Calculate duration in milliseconds
        start_time_ns = otel_span.start_time or 0
        end_time_ns = otel_span.end_time or start_time_ns
        duration_ms = int((end_time_ns - start_time_ns) / 1_000_000)

        # Convert attributes to dictionary
        attributes = {}
        if otel_span.attributes:
            for key, value in otel_span.attributes.items():
                # Convert attribute values to JSON-serializable types
                if isinstance(value, (str, int, float, bool, type(None))):
                    attributes[key] = value
                elif isinstance(value, (list, tuple)):
                    attributes[key] = list(value)
                else:
                    attributes[key] = str(value)

        # Convert events to list of dictionaries
        events = []
        if otel_span.events:
            for event in otel_span.events:
                event_dict = {
                    "name": event.name,
                    "timestamp": event.timestamp,
                    "attributes": dict(event.attributes) if event.attributes else {},
                }
                events.append(event_dict)

        return cls(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            name=otel_span.name,
            span_kind=span_kind,
            status_code=status_code,
            status_message=status_message,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            duration_ms=duration_ms,
            attributes=attributes,
            events=events,
            created_at=int(time()),
        )


def create_trace_from_spans(spans: List[Span]) -> Optional[Trace]:
    """
    Create a Trace object from a list of Span objects with the same trace_id.

    Args:
        spans: List of Span objects belonging to the same trace

    Returns:
        Trace object with aggregated information, or None if spans list is empty
    """
    if not spans:
        return None

    # Find root span (no parent)
    root_span = next((s for s in spans if not s.parent_span_id), spans[0])

    # Calculate aggregated metrics
    trace_id = spans[0].trace_id
    start_time_ns = min(s.start_time_ns for s in spans)
    end_time_ns = max(s.end_time_ns for s in spans)
    duration_ms = int((end_time_ns - start_time_ns) / 1_000_000)
    total_spans = len(spans)
    error_count = sum(1 for s in spans if s.status_code == "ERROR")

    # Determine overall status (ERROR if any span errored, OK otherwise)
    status = "ERROR" if error_count > 0 else "OK"

    # Extract context from root span's attributes
    attrs = root_span.attributes
    run_id = attrs.get("run_id") or attrs.get("agno.run.id")

    session_id = attrs.get("session_id") or attrs.get("agno.session.id") or attrs.get("session.id")

    user_id = attrs.get("user_id") or attrs.get("agno.user.id") or attrs.get("user.id")

    # Try to extract agent_id from the span name or attributes
    agent_id = attrs.get("agent_id") or attrs.get("agno.agent.id")

    return Trace(
        trace_id=trace_id,
        name=root_span.name,
        status=status,
        start_time_ns=start_time_ns,
        end_time_ns=end_time_ns,
        duration_ms=duration_ms,
        total_spans=total_spans,
        error_count=error_count,
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        agent_id=agent_id,
        created_at=int(time()),
    )
