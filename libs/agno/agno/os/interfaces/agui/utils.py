import ast
import json
from typing import Optional


def to_json_str(value: Optional[str]) -> str:
    # Tool results arrive as strings but may be Python repr format ("{'key': 'value'}")
    # because base.py uses str(dict). Frontend needs valid JSON for JSON.parse().

    if value is None:
        return "null"

    # 1. Already valid JSON — pass through unchanged
    try:
        json.loads(value)
        return value
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Python repr — parse with ast.literal_eval (safe, literals only), then serialize as JSON
    # Handles: "{'a': 1}" → {"a": 1}, "True" → true, "None" → null
    try:
        obj = ast.literal_eval(value)
        return json.dumps(obj)
    except (ValueError, SyntaxError):
        pass

    # 3. Plain string — wrap as JSON string literal
    return json.dumps(value)
