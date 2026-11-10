"""Generic FilterExpr -> database query converter for named table columns.

Converts serialized FilterExpr dictionaries (from agno.filters) to database-native
predicates that can be applied to any table with named columns.

This is distinct from PgVector's _dsl_to_sqlalchemy which operates on JSONB metadata
columns. This converter operates on direct table columns (table.c.column_name).

Supported backends:
    - SQLAlchemy (SQLite, PostgreSQL, MySQL, SingleStore)

Usage:
    >>> from agno.db.filter_converter import filter_expr_to_sqlalchemy, TRACE_COLUMNS
    >>>
    >>> # Convert a filter dict to a SQLAlchemy WHERE clause
    >>> filter_dict = {"op": "AND", "conditions": [
    ...     {"op": "EQ", "key": "status", "value": "OK"},
    ...     {"op": "CONTAINS", "key": "user_id", "value": "admin"}
    ... ]}
    >>> where_clause = filter_expr_to_sqlalchemy(filter_dict, table, TRACE_COLUMNS)
    >>> stmt = select(table).where(where_clause)
"""

from typing import Any, Dict, Optional, Set

# Maximum recursion depth for nested filter expressions (prevents stack overflow attacks)
MAX_FILTER_DEPTH: int = 10

# Valid column names per entity type (for field validation)
TRACE_COLUMNS: Set[str] = {
    "trace_id",
    "name",
    "status",
    "start_time",
    "end_time",
    "duration_ms",
    "run_id",
    "session_id",
    "user_id",
    "agent_id",
    "team_id",
    "workflow_id",
    "created_at",
}

# Columns that store ISO 8601 datetime strings in UTC.
# Filter values for these columns are normalized to UTC before comparison
# so that timezone-aware inputs (e.g. "+05:30") compare correctly against
# the stored UTC strings via lexicographic ordering.
DATETIME_COLUMNS: Set[str] = {"start_time", "end_time", "created_at"}


def _normalize_datetime_value(value: Any) -> Any:
    """Parse an ISO 8601 string and return it in UTC for consistent comparison."""
    from agno.utils.dttm import parse_datetime_utc

    try:
        return parse_datetime_utc(value).isoformat()
    except (TypeError, ValueError):
        return value


def filter_expr_to_sqlalchemy(
    filter_dict: Dict[str, Any],
    table: Any,
    allowed_columns: Optional[Set[str]] = None,
    _depth: int = 0,
) -> Any:
    """Convert a FilterExpr dict to a SQLAlchemy WHERE clause on named table columns.

    Args:
        filter_dict: Serialized FilterExpr (from to_dict() or JSON body).
        table: SQLAlchemy Table object.
        allowed_columns: Set of allowed column names for validation.
            If provided, raises ValueError for unknown columns.
        _depth: Internal parameter tracking recursion depth. Do not pass manually.

    Returns:
        SQLAlchemy ColumnElement that can be passed to .where().

    Raises:
        ValueError: If filter_dict has invalid structure, unknown operator,
            references a column not in allowed_columns, or exceeds max recursion depth.
    """
    from sqlalchemy import and_, func, not_, or_

    # Check recursion depth limit
    if _depth > MAX_FILTER_DEPTH:
        raise ValueError(f"Filter expression exceeds maximum nesting depth of {MAX_FILTER_DEPTH}")

    if not isinstance(filter_dict, dict) or "op" not in filter_dict:
        raise ValueError(f"Invalid filter: must be a dict with 'op' key. Got: {filter_dict}")

    op = filter_dict["op"]

    # Single-field operators
    if op in ("EQ", "NEQ", "GT", "GTE", "LT", "LTE", "CONTAINS", "STARTSWITH"):
        key = filter_dict.get("key")
        value = filter_dict.get("value")

        if key is None or value is None:
            raise ValueError(f"{op} filter requires 'key' and 'value' fields. Got: {filter_dict}")

        # Field validation
        if allowed_columns and key not in allowed_columns:
            raise ValueError(f"Invalid filter field: '{key}'. Allowed: {sorted(allowed_columns)}")

        # Normalize timezone-aware datetime strings to UTC so that
        # lexicographic comparison against stored UTC values is correct.
        if key in DATETIME_COLUMNS:
            value = _normalize_datetime_value(value)

        col = table.c[key]

        if op == "EQ":
            return col == value
        elif op == "NEQ":
            return col != value
        elif op == "GT":
            return col > value
        elif op == "GTE":
            return col >= value
        elif op == "LT":
            return col < value
        elif op == "LTE":
            return col <= value
        elif op == "CONTAINS":
            # Case-insensitive substring match with autoescape to prevent SQL wildcard injection
            return func.lower(col).contains(str(value).lower(), autoescape=True)
        elif op == "STARTSWITH":
            # Case-insensitive prefix match with autoescape to prevent SQL wildcard injection
            return func.lower(col).startswith(str(value).lower(), autoescape=True)

    elif op == "IN":
        key = filter_dict.get("key")
        values = filter_dict.get("values")

        if key is None or values is None:
            raise ValueError(f"IN filter requires 'key' and 'values' fields. Got: {filter_dict}")

        if allowed_columns and key not in allowed_columns:
            raise ValueError(f"Invalid filter field: '{key}'. Allowed: {sorted(allowed_columns)}")

        if key in DATETIME_COLUMNS:
            values = [_normalize_datetime_value(v) for v in values]

        return table.c[key].in_(values)

    elif op == "AND":
        conditions = filter_dict.get("conditions")
        if not conditions:
            raise ValueError(f"AND filter requires 'conditions' field. Got: {filter_dict}")
        return and_(*[filter_expr_to_sqlalchemy(c, table, allowed_columns, _depth + 1) for c in conditions])

    elif op == "OR":
        conditions = filter_dict.get("conditions")
        if not conditions:
            raise ValueError(f"OR filter requires 'conditions' field. Got: {filter_dict}")
        return or_(*[filter_expr_to_sqlalchemy(c, table, allowed_columns, _depth + 1) for c in conditions])

    elif op == "NOT":
        condition = filter_dict.get("condition")
        if not condition:
            raise ValueError(f"NOT filter requires 'condition' field. Got: {filter_dict}")
        return not_(filter_expr_to_sqlalchemy(condition, table, allowed_columns, _depth + 1))

    else:
        raise ValueError(f"Unknown filter operator: {op}")
