"""Validation and portable predicates for advanced session searches."""

import math
from types import SimpleNamespace
from typing import Any, Dict, Optional

from agno.db.filter_converter import MAX_FILTER_DEPTH, filter_expr_to_sqlalchemy
from agno.utils.dttm import parse_datetime_utc

STRING_OPERATORS = ["EQ", "NEQ", "IN", "CONTAINS", "STARTSWITH"]
SESSION_FILTER_FIELDS: Dict[str, Dict[str, Any]] = {
    key: {"label": label, "type": "string", "operators": STRING_OPERATORS}
    for key, label in [
        ("session_id", "Session ID"),
        ("session_name", "Session Name"),
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


def session_filter_to_sqlalchemy(expression: Dict[str, Any], table: Any) -> Any:
    """Use native columns and the session-name JSON property for SQL filtering."""
    normalized = normalize_session_filter(expression)
    assert normalized is not None
    columns = {key: table.c[key] for key in SESSION_FILTER_FIELDS if key != "session_name"}
    columns["session_name"] = table.c.session_data["session_name"].as_string()
    return filter_expr_to_sqlalchemy(normalized, SimpleNamespace(c=columns), set(SESSION_FILTER_FIELDS))


def matches_session_filter(session: Dict[str, Any], expression: Optional[Dict[str, Any]]) -> bool:
    """Evaluate a validated filter for adapters without native search support."""
    if expression is None:
        return True
    op = expression["op"]
    if op == "AND":
        return all(matches_session_filter(session, c) for c in expression["conditions"])
    if op == "OR":
        return any(matches_session_filter(session, c) for c in expression["conditions"])
    key = expression["key"]
    actual = (session.get("session_data") or {}).get("session_name") if key == "session_name" else session.get(key)
    # Match SQL's treatment of NULL: missing fields do not satisfy comparisons.
    if actual is None:
        return False
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
