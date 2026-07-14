"""Helpers for reading the active OpenTelemetry context.

Kept free of any opentelemetry-sdk or agno.tracing imports so it is safe to
use in the run hot path whether or not tracing is installed or enabled.
"""

from typing import Optional

try:
    from opentelemetry import trace as _trace_api  # type: ignore

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


def get_current_trace_id() -> Optional[str]:
    """Return the trace_id of the current OpenTelemetry span, if there is one.

    Returns the 32-character lowercase hex form (the format used by OTLP
    backends like Langfuse, Arize Phoenix and MLflow, and by Agno's trace
    tables). Returns None when OpenTelemetry is not installed, tracing is not
    set up, or there is no span in the current context.
    """
    if not OTEL_AVAILABLE:
        return None
    span_context = _trace_api.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return format(span_context.trace_id, "032x")
