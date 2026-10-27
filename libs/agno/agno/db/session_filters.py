"""Validation and portable predicates for advanced session searches."""

import math
import re
from types import SimpleNamespace
from typing import Any, Dict, Optional

from agno.db.filter_converter import MAX_FILTER_DEPTH, filter_expr_to_sqlalchemy
from agno.utils.dttm import parse_datetime_utc

STRING_OPERATORS = ["EQ", "NEQ", "IN", "CONTAINS", "STARTSWITH"]
SESSION_FILTER_FIELDS: Dict[str, Dict[str, Any]] = {
    key: {"label": label, "type": "string", "operators": STRING_OPERATORS}
    for key, label in [
        ("session_id", "Session ID"),
        ("session_name", "Saved Session Name"),
        ("user_id", "User ID"),
        ("agent_id", "Agent ID"),
        ("team_id", "Team ID"),
        ("workflow_id", "Workflow ID"),
    ]
}
SESSION_FILTER_FIELDS["session_type"] = {
    "label": "Session Type",
    "type": "enum",
    "operators": ["EQ", "NEQ", "IN"],
    "values": ["agent", "team", "workflow"],
}
for key, label in [("created_at", "Created At"), ("updated_at", "Updated At")]:
    SESSION_FILTER_FIELDS[key] = {
        "label": label,
        "type": "datetime",
        "operators": ["EQ", "NEQ", "GT", "GTE", "LT", "LTE"],
    }


def normalize_session_filter(expression: Optional[Dict[str, Any]], _depth: int = 0) -> Optional[Dict[str, Any]]:
    """Validate every node before querying, and convert dates to epoch seconds."""
    if expression is None and _depth == 0:
        return None
    if _depth > MAX_FILTER_DEPTH:
        raise ValueError("Session filter exceeds maximum nesting depth")
    if not isinstance(expression, dict):
        raise ValueError("Each filter must be an object")
    op = expression.get("op")
    if op in ("AND", "OR"):
        conditions = expression.get("conditions")
        if not isinstance(conditions, list) or not conditions or len(conditions) > 100:
            raise ValueError("AND/OR require between 1 and 100 conditions")
        return {"op": op, "conditions": [normalize_session_filter(c, _depth + 1) for c in conditions]}
    if op == "NOT":
        return {"op": op, "condition": normalize_session_filter(expression.get("condition"), _depth + 1)}
    key = expression.get("key")
    if not isinstance(key, str) or key not in SESSION_FILTER_FIELDS:
        raise ValueError(f"Unknown session filter field: {key}")
    field = SESSION_FILTER_FIELDS[key]
    if op not in field["operators"]:
        raise ValueError(f"Unsupported operator for {key}: {op}")
    values = expression.get("values") if op == "IN" else [expression.get("value")]
    if not isinstance(values, list) or not values or len(values) > 100:
        raise ValueError("IN requires between 1 and 100 values")
    normalized = []
    for value in values:
        if field["type"] == "datetime":
            if isinstance(value, bool):
                raise ValueError(f"Invalid timestamp for {key}")
            try:
                value = value if isinstance(value, (int, float)) else parse_datetime_utc(value).timestamp()
                if not math.isfinite(value):
                    raise ValueError("Timestamp must be finite")
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Invalid timestamp for {key}") from exc
        elif not isinstance(value, str):
            raise ValueError(f"{key} requires string values")
        if field["type"] == "enum" and value not in field["values"]:
            raise ValueError(f"Invalid value for {key}: {value}")
        normalized.append(value)
    return {"op": op, "key": key, **({"values": normalized} if op == "IN" else {"value": normalized[0]})}


def session_filter_to_sqlalchemy(
    expression: Dict[str, Any],
    table: Any,
    collation: Optional[str] = None,
    session_name_column: Any = None,
    backslash_like: bool = False,
) -> Any:
    """Use native columns and the session-name JSON property for SQL filtering on a normalized filter.

    ``collation`` forces case-sensitive string comparison where the database default is case-insensitive.
    ``session_name_column`` replaces the generic JSON accessor for dialects without MySQL/Postgres JSON functions.
    ``backslash_like`` escapes LIKE wildcards with a backslash instead of an ESCAPE clause the dialect may reject.
    """
    columns = {key: table.c[key] for key in SESSION_FILTER_FIELDS if key != "session_name"}
    if session_name_column is None:
        session_name_column = table.c.session_data["session_name"].as_string()
    columns["session_name"] = session_name_column
    if collation is not None:
        for key, field in SESSION_FILTER_FIELDS.items():
            if field["type"] != "datetime":
                columns[key] = columns[key].collate(collation)
    view = SimpleNamespace(c=columns)
    if backslash_like:
        return _backslash_like_filter(expression, view)
    return filter_expr_to_sqlalchemy(expression, view, set(SESSION_FILTER_FIELDS))


def _backslash_like_filter(expression: Dict[str, Any], view: Any) -> Any:
    """Build the clause with CONTAINS/STARTSWITH as plain LIKE using the default backslash escape."""
    from sqlalchemy import and_, func, not_, or_

    op = expression["op"]
    if op in ("AND", "OR"):
        clauses = [_backslash_like_filter(c, view) for c in expression["conditions"]]
        return and_(*clauses) if op == "AND" else or_(*clauses)
    if op == "NOT":
        return not_(_backslash_like_filter(expression["condition"], view))
    if op in ("CONTAINS", "STARTSWITH"):
        escaped = re.sub(r"([\\%_])", r"\\\1", str(expression["value"]).lower())
        pattern = ("" if op == "STARTSWITH" else "%") + escaped + "%"
        return func.lower(view.c[expression["key"]]).like(pattern)
    return filter_expr_to_sqlalchemy(expression, view, set(SESSION_FILTER_FIELDS))


def session_filter_to_mongo(expression: Dict[str, Any], negate: bool = False) -> Dict[str, Any]:
    """Translate a normalized filter to a MongoDB query with SQL NULL semantics.

    NOT is pushed down to the leaves, and every leaf requires a value of the field's type, so a
    missing value never matches a comparison or its negation.
    """
    op = expression["op"]
    if op in ("AND", "OR"):
        parts = [session_filter_to_mongo(c, negate) for c in expression["conditions"]]
        return {"$and" if (op == "AND") != negate else "$or": parts}
    if op == "NOT":
        return session_filter_to_mongo(expression["condition"], not negate)
    key = expression["key"]
    field = "session_data.session_name" if key == "session_name" else key
    condition: Any
    if op == "IN":
        condition = {"$nin" if negate else "$in": expression["values"]}
    elif op in ("CONTAINS", "STARTSWITH"):
        regex = re.compile(("^" if op == "STARTSWITH" else "") + re.escape(expression["value"]), re.IGNORECASE)
        condition = {"$not": regex} if negate else regex
    else:
        comparisons = {"EQ": "$eq", "NEQ": "$ne", "GT": "$gt", "GTE": "$gte", "LT": "$lt", "LTE": "$lte"}
        opposites = {"EQ": "$ne", "NEQ": "$eq", "GT": "$lte", "GTE": "$lt", "LT": "$gte", "LTE": "$gt"}
        condition = {(opposites if negate else comparisons)[op]: expression["value"]}
    value_type = "number" if SESSION_FILTER_FIELDS[key]["type"] == "datetime" else "string"
    return {"$and": [{field: {"$type": value_type}}, {field: condition}]}


def matches_session_filter(session: Dict[str, Any], expression: Optional[Dict[str, Any]]) -> bool:
    """Evaluate a validated filter for adapters without native search support."""
    return _evaluate_session_filter(session, expression) is True


def _evaluate_session_filter(session: Dict[str, Any], expression: Optional[Dict[str, Any]]) -> Optional[bool]:
    """Preserve SQL's unknown result for NULL comparisons, including under NOT."""
    if expression is None:
        return True
    op = expression["op"]
    if op in ("AND", "OR"):
        results = [_evaluate_session_filter(session, c) for c in expression["conditions"]]
        if op == "AND":
            return False if False in results else None if None in results else True
        return True if True in results else None if None in results else False
    if op == "NOT":
        result = _evaluate_session_filter(session, expression["condition"])
        return None if result is None else not result
    key = expression["key"]
    actual = session.get(key)
    if key == "session_name" and actual is None:
        # SurrealDB renames write a top-level session_name; other adapters keep it in session_data.
        actual = (session.get("session_data") or {}).get("session_name")
    if actual is None:
        return None
    if op == "IN":
        return actual in expression["values"]
    value = expression["value"]
    if op == "EQ":
        return actual == value
    if op == "NEQ":
        return actual != value
    if op == "GT":
        return actual > value
    if op == "GTE":
        return actual >= value
    if op == "LT":
        return actual < value
    if op == "LTE":
        return actual <= value
    if op == "CONTAINS":
        return value.lower() in actual.lower()
    return actual.lower().startswith(value.lower())
