"""
Trace data models for Agno tracing.
"""

from dataclasses import asdict, dataclass
from time import time
from typing import Any, Dict, List, Optional

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind, StatusCode


@dataclass
class TraceSpan:
    """Represents a single span in a distributed trace"""

    trace_id: str
    span_id: str
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
    run_id: Optional[str]
    session_id: Optional[str]
    user_id: Optional[str]
    agent_id: Optional[str]
    created_at: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert TraceSpan to dictionary for database storage"""
        return asdict(self)

    @classmethod
    def from_otel_span(cls, otel_span: ReadableSpan) -> "TraceSpan":
        """Convert OpenTelemetry ReadableSpan to TraceSpan"""
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

        # Extract Agno-specific attributes
        run_id = attributes.get("run_id") or attributes.get("agno.run.id")
        session_id = attributes.get("session_id") or attributes.get("agno.session.id")
        user_id = attributes.get("user_id") or attributes.get("agno.user.id")
        agent_id = attributes.get("agent_id") or attributes.get("agno.agent.id")

        return cls(
            trace_id=trace_id,
            span_id=span_id,
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
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            created_at=int(time()),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceSpan":
        """Create TraceSpan from dictionary"""
        return cls(
            trace_id=data["trace_id"],
            span_id=data["span_id"],
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
            run_id=data.get("run_id"),
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            agent_id=data.get("agent_id"),
            created_at=data["created_at"],
        )

