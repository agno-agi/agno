import ast
import json


def to_json_str(value: str) -> str:
    """Convert a string value to valid JSON for frontend parsing.

    Tool results arrive as strings that may be Python repr format,
    already valid JSON, or plain strings. This normalizes them to
    valid JSON that JavaScript can JSON.parse().
    """
    # 1. Already valid JSON
    try:
        json.loads(value)
        return value
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Python repr (dict/list/bool/None)
    try:
        obj = ast.literal_eval(value)
        return json.dumps(obj)
    except (ValueError, SyntaxError):
        pass

    # 3. Plain string
    return json.dumps(value)
