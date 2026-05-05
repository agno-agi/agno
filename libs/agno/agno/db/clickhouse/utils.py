"""Helpers for converting between Agno Trace/Span dataclasses and ClickHouse rows."""

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Sequence, Tuple

from agno.db.clickhouse.schemas import SPAN_COLUMNS, TRACE_COLUMNS

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace


def _to_aware_datetime(value: Any) -> datetime:
    """Coerce a datetime-or-iso-string into a tz-aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported datetime value: {value!r}")


def trace_to_row(trace: "Trace") -> Tuple[Any, ...]:
    """Build a positional row for inserting into the traces table."""
    return (
        trace.trace_id,
        trace.name,
        trace.status,
        _to_aware_datetime(trace.start_time),
        _to_aware_datetime(trace.end_time),
        int(trace.duration_ms),
        trace.run_id,
        trace.session_id,
        trace.user_id,
        trace.agent_id,
        trace.team_id,
        trace.workflow_id,
        _to_aware_datetime(trace.created_at),
    )


def span_to_row(span: "Span") -> Tuple[Any, ...]:
    """Build a positional row for inserting into the spans table.

    ``attributes`` is JSON-encoded because ClickHouse doesn't ship a native
    JSON column type that's stable across all server versions; the experimental
    ``JSON`` type would tie users to a specific build. Storing it as ``String``
    keeps the schema portable, and queries can still use ``JSONExtract*``.
    """
    return (
        span.span_id,
        span.trace_id,
        span.parent_span_id,
        span.name,
        span.span_kind,
        span.status_code,
        span.status_message,
        _to_aware_datetime(span.start_time),
        _to_aware_datetime(span.end_time),
        int(span.duration_ms),
        json.dumps(span.attributes or {}, default=str),
        _to_aware_datetime(span.created_at),
    )


def row_to_trace(row: Dict[str, Any], total_spans: int = 0, error_count: int = 0) -> "Trace":
    """Inflate a result row into a Trace dataclass."""
    from agno.tracing.schemas import Trace

    return Trace(
        trace_id=row["trace_id"],
        name=row["name"],
        status=row["status"],
        start_time=_to_aware_datetime(row["start_time"]),
        end_time=_to_aware_datetime(row["end_time"]),
        duration_ms=int(row["duration_ms"]),
        total_spans=int(total_spans),
        error_count=int(error_count),
        run_id=row.get("run_id"),
        session_id=row.get("session_id"),
        user_id=row.get("user_id"),
        agent_id=row.get("agent_id"),
        team_id=row.get("team_id"),
        workflow_id=row.get("workflow_id"),
        created_at=_to_aware_datetime(row["created_at"]),
    )


def row_to_span(row: Dict[str, Any]) -> "Span":
    """Inflate a result row into a Span dataclass."""
    from agno.tracing.schemas import Span

    raw_attrs = row.get("attributes")
    if isinstance(raw_attrs, str) and raw_attrs:
        try:
            attributes = json.loads(raw_attrs)
        except json.JSONDecodeError:
            attributes = {}
    elif isinstance(raw_attrs, dict):
        attributes = raw_attrs
    else:
        attributes = {}

    return Span(
        span_id=row["span_id"],
        trace_id=row["trace_id"],
        parent_span_id=row.get("parent_span_id"),
        name=row["name"],
        span_kind=row["span_kind"],
        status_code=row["status_code"],
        status_message=row.get("status_message"),
        start_time=_to_aware_datetime(row["start_time"]),
        end_time=_to_aware_datetime(row["end_time"]),
        duration_ms=int(row["duration_ms"]),
        attributes=attributes,
        created_at=_to_aware_datetime(row["created_at"]),
    )


def named_rows(column_names: Sequence[str], rows: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Zip column names with positional rows from clickhouse-connect results."""
    return [dict(zip(column_names, r)) for r in rows]


def trace_columns() -> List[str]:
    return list(TRACE_COLUMNS)


def span_columns() -> List[str]:
    return list(SPAN_COLUMNS)
