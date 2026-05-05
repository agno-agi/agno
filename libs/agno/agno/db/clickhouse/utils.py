"""Helpers for converting between Agno Trace/Span dataclasses and ClickHouse rows."""

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from agno.db.clickhouse.schemas import SPAN_COLUMNS, TRACE_COLUMNS

# ClickHouse datetime columns. Filter values for these columns get parsed
# from ISO 8601 strings to tz-aware datetimes before binding so the server's
# DateTime64(6, 'UTC') column accepts them.
DATETIME_COLUMNS = {"start_time", "end_time", "created_at"}

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


def coerce_datetime(value: Any) -> Optional[datetime]:
    """Best-effort coercion to a tz-aware UTC datetime for binding.

    Accepts ``datetime`` (naive treated as UTC), ISO 8601 strings (with or
    without trailing ``Z``), and integer/float epoch seconds. Returns ``None``
    if ``value`` is ``None``. Raises on anything else so callers don't bind
    silently-invalid values.
    """
    from agno.utils.dttm import parse_datetime_utc

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return parse_datetime_utc(value)


def named_rows(column_names: Sequence[str], rows: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Zip column names with positional rows from clickhouse-connect results."""
    return [dict(zip(column_names, r)) for r in rows]


def trace_columns() -> List[str]:
    return list(TRACE_COLUMNS)


def span_columns() -> List[str]:
    return list(SPAN_COLUMNS)


# --------------------------------------------------------------------------- #
# FilterExpr -> ClickHouse SQL fragment
# --------------------------------------------------------------------------- #
#
# Mirrors `agno.db.filter_converter.filter_expr_to_sqlalchemy` but emits a
# parameterized SQL fragment compatible with `clickhouse-connect`. Column
# names are validated against ``allowed_columns`` (no string interpolation
# of arbitrary keys); values flow through ``%(name)s`` placeholders so the
# server-side parser handles escaping.

MAX_FILTER_DEPTH = 10
_OP_TO_SQL = {
    "EQ": "=",
    "NEQ": "!=",
    "GT": ">",
    "GTE": ">=",
    "LT": "<",
    "LTE": "<=",
}


def filter_expr_to_clickhouse(
    filter_dict: Dict[str, Any],
    params: Dict[str, Any],
    allowed_columns: set,
    column_alias: str = "",
    _depth: int = 0,
    _counter: List[int] = None,  # type: ignore[assignment]
) -> str:
    """Convert a FilterExpr dict to a parameterized ClickHouse WHERE fragment.

    Args:
        filter_dict: Serialized FilterExpr (from ``to_dict()`` or JSON).
        params: Mutable dict that the function appends parameters into.
        allowed_columns: Whitelist of column names; unknown columns raise.
        column_alias: Optional table alias (e.g. ``"t"``) prefixed to columns.
        _depth: Internal recursion-depth tracker.
        _counter: Internal placeholder-name counter (mutable list of length 1).

    Returns:
        A SQL fragment string; ``params`` is updated in place with the values.

    Raises:
        ValueError: On invalid structure, unknown operator, or unknown column.
    """
    if _depth > MAX_FILTER_DEPTH:
        raise ValueError(f"Filter expression exceeds maximum nesting depth of {MAX_FILTER_DEPTH}")
    if _counter is None:
        _counter = [0]

    if not isinstance(filter_dict, dict) or "op" not in filter_dict:
        raise ValueError(f"Invalid filter: must be a dict with 'op' key. Got: {filter_dict}")

    op = filter_dict["op"]
    prefix = f"{column_alias}." if column_alias else ""

    def _next_param() -> str:
        _counter[0] += 1
        return f"__filter_{_counter[0]}"

    def _check_column(key: str) -> str:
        if key not in allowed_columns:
            raise ValueError(f"Invalid filter field: '{key}'. Allowed: {sorted(allowed_columns)}")
        return f"{prefix}{key}"

    if op in _OP_TO_SQL:
        key = filter_dict.get("key")
        value = filter_dict.get("value")
        if key is None or value is None:
            raise ValueError(f"{op} filter requires 'key' and 'value' fields. Got: {filter_dict}")
        col = _check_column(key)
        pname = _next_param()
        if key in DATETIME_COLUMNS:
            value = coerce_datetime(value)
        params[pname] = value
        return f"{col} {_OP_TO_SQL[op]} %({pname})s"

    if op == "CONTAINS":
        key = filter_dict.get("key")
        value = filter_dict.get("value")
        if key is None or value is None:
            raise ValueError(f"CONTAINS filter requires 'key' and 'value' fields. Got: {filter_dict}")
        col = _check_column(key)
        pname = _next_param()
        params[pname] = str(value).lower()
        # positionCaseInsensitive returns a 1-based offset; > 0 means "found".
        return f"positionCaseInsensitive(toString({col}), %({pname})s) > 0"

    if op == "STARTSWITH":
        key = filter_dict.get("key")
        value = filter_dict.get("value")
        if key is None or value is None:
            raise ValueError(f"STARTSWITH filter requires 'key' and 'value' fields. Got: {filter_dict}")
        col = _check_column(key)
        pname = _next_param()
        params[pname] = str(value).lower()
        return f"startsWith(lower(toString({col})), %({pname})s)"

    if op == "IN":
        key = filter_dict.get("key")
        values = filter_dict.get("values")
        if key is None or values is None:
            raise ValueError(f"IN filter requires 'key' and 'values' fields. Got: {filter_dict}")
        col = _check_column(key)
        pname = _next_param()
        if key in DATETIME_COLUMNS:
            params[pname] = [coerce_datetime(v) for v in values]
        else:
            params[pname] = list(values)
        return f"{col} IN %({pname})s"

    if op == "AND":
        conditions = filter_dict.get("conditions")
        if not conditions:
            raise ValueError(f"AND filter requires 'conditions' field. Got: {filter_dict}")
        parts = [
            filter_expr_to_clickhouse(c, params, allowed_columns, column_alias, _depth + 1, _counter)
            for c in conditions
        ]
        return "(" + " AND ".join(parts) + ")"

    if op == "OR":
        conditions = filter_dict.get("conditions")
        if not conditions:
            raise ValueError(f"OR filter requires 'conditions' field. Got: {filter_dict}")
        parts = [
            filter_expr_to_clickhouse(c, params, allowed_columns, column_alias, _depth + 1, _counter)
            for c in conditions
        ]
        return "(" + " OR ".join(parts) + ")"

    if op == "NOT":
        condition = filter_dict.get("condition")
        if not condition:
            raise ValueError(f"NOT filter requires 'condition' field. Got: {filter_dict}")
        inner = filter_expr_to_clickhouse(
            condition, params, allowed_columns, column_alias, _depth + 1, _counter
        )
        return f"NOT ({inner})"

    raise ValueError(f"Unknown filter operator: {op}")
