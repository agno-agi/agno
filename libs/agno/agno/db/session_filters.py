"""Validation and portable predicates for advanced session searches."""

import json
import math
import re
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

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
SESSION_FILTER_FIELDS["summary"] = {"label": "Session Summary", "type": "string", "operators": ["CONTAINS"]}
SESSION_FILTER_FIELDS["run_content"] = {"label": "Conversation", "type": "string", "operators": ["CONTAINS"]}
# Fields read from a property of a JSON column rather than from a column of their own.
JSON_SESSION_FIELDS: Dict[str, Tuple[str, str]] = {
    "session_name": ("session_data", "session_name"),
    "summary": ("summary", "summary"),
}
# What run_content searches: each run's final answer and the input it was given, not the system
# prompt or tool traffic, which repeat across runs and would match nearly every session.
RUN_CONTENT_PATHS: Tuple[Tuple[str, ...], ...] = (("content",), ("input", "input_content"))
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
    json_property: Optional[Callable[..., Any]] = None,
    runs_table: Any = None,
) -> Any:
    """Use native columns and JSON properties for SQL filtering on a normalized filter.

    ``collation`` forces case-sensitive string comparison where the database default is case-insensitive.
    ``json_property(column, *path)`` replaces the generic JSON accessor for dialects without MySQL/Postgres
    JSON functions; ``session_name_column`` overrides it for the session name only.
    ``backslash_like`` escapes LIKE wildcards with a backslash instead of an ESCAPE clause the dialect may reject.
    ``runs_table`` holds the runs that ``run_content`` searches; without it no run content matches.
    """
    from sqlalchemy import exists, false, literal, or_, select

    accessor = json_property or _json_text
    columns = {
        key: table.c[key] for key in SESSION_FILTER_FIELDS if key not in JSON_SESSION_FIELDS and key != "run_content"
    }
    for key, (column, name) in JSON_SESSION_FIELDS.items():
        columns[key] = accessor(table.c[column], name)
    if session_name_column is not None:
        columns["session_name"] = session_name_column
    if collation is not None:
        for key in columns:
            if SESSION_FILTER_FIELDS[key]["type"] != "datetime":
                columns[key] = columns[key].collate(collation)
    view = SimpleNamespace(c=columns)

    def run_content(value: str) -> Any:
        if runs_table is None:
            return false()
        texts = [accessor(runs_table.c.run_data, *path) for path in RUN_CONTENT_PATHS]
        matches = or_(*[_like(text, "CONTAINS", value, backslash_like) for text in texts])
        return exists(select(literal(1)).where(runs_table.c.session_id == table.c.session_id, matches))

    return _to_sqlalchemy(expression, view, backslash_like, run_content)


def _json_text(column: Any, *path: str) -> Any:
    return (column[path[0]] if len(path) == 1 else column[path]).as_string()


def _like(column: Any, op: str, value: Any, backslash_like: bool) -> Any:
    """Case-insensitive CONTAINS/STARTSWITH with LIKE wildcards in the value escaped."""
    from sqlalchemy import func

    lowered = str(value).lower()
    if backslash_like:
        escaped = re.sub(r"([\\%_])", r"\\\1", lowered)
        return func.lower(column).like(("" if op == "STARTSWITH" else "%") + escaped + "%")
    if op == "STARTSWITH":
        return func.lower(column).startswith(lowered, autoescape=True)
    return func.lower(column).contains(lowered, autoescape=True)


def _to_sqlalchemy(expression: Dict[str, Any], view: Any, backslash_like: bool, run_content: Callable) -> Any:
    from sqlalchemy import and_, not_, or_

    op = expression["op"]
    if op in ("AND", "OR"):
        clauses = [_to_sqlalchemy(c, view, backslash_like, run_content) for c in expression["conditions"]]
        return and_(*clauses) if op == "AND" else or_(*clauses)
    if op == "NOT":
        return not_(_to_sqlalchemy(expression["condition"], view, backslash_like, run_content))
    if expression["key"] == "run_content":
        return run_content(expression["value"])
    if backslash_like and op in ("CONTAINS", "STARTSWITH"):
        return _like(view.c[expression["key"]], op, expression["value"], True)
    return filter_expr_to_sqlalchemy(expression, view, set(view.c))


def mentions_run_content(expression: Optional[Dict[str, Any]]) -> bool:
    """True when a normalized filter searches run content anywhere in its tree."""
    if expression is None:
        return False
    if expression["op"] in ("AND", "OR"):
        return any(mentions_run_content(c) for c in expression["conditions"])
    if expression["op"] == "NOT":
        return mentions_run_content(expression["condition"])
    return expression["key"] == "run_content"


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
    if key == "run_content":
        raise ValueError("Run content lives outside the session document; search it through the portable fallback")
    field = ".".join(JSON_SESSION_FIELDS[key]) if key in JSON_SESSION_FIELDS else key
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
    if key == "run_content":
        # EXISTS semantics: a session without matching runs is False, never unknown.
        needle = expression["value"].lower()
        return any(needle in text.lower() for run in session.get("runs") or [] for text in _run_texts(run))
    if key in JSON_SESSION_FIELDS:
        # SurrealDB renames write a top-level session_name; other adapters keep it in session_data.
        actual = session.get(key) if key == "session_name" else None
        if actual is None:
            column, name = JSON_SESSION_FIELDS[key]
            container = session.get(column)
            actual = container.get(name) if isinstance(container, dict) else None
        if not isinstance(actual, str):
            return None
    else:
        actual = session.get(key)
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


def _run_texts(run: Any) -> List[str]:
    data = run if isinstance(run, dict) else run.to_dict() if hasattr(run, "to_dict") else {}
    texts = []
    for path in RUN_CONTENT_PATHS:
        value: Any = data
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, str):
            texts.append(value)
        elif value is not None:
            texts.append(json.dumps(value, default=str))
    return texts
