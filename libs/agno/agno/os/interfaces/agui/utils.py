import ast
import json
from typing import Any, Optional

from agno.utils.log import log_warning


def readable(value: Any, described: str) -> Optional[str]:
    """A value as display text, or None when it is falsy or reading it raises.

    A name reaches the chunk straight off the caller's own Agent or Team, and
    the words a pause advertises its answer shape in come off whatever a tool
    declared, so rendering one can raise. A label is never worth ending a run
    for, so a value that cannot be read is recorded and treated as absent.

    Falsy is absent too, and deliberately: every caller is choosing a label, and
    the empty string, an empty mapping and zero are all nothing to show, so each
    of them falls through to whatever the caller offers next rather than
    reaching the wire as ``""`` or ``"0"``. A caller that has to tell an empty
    value from a missing one cannot use this.

    Shared by the stream's labels and the interrupt round trip's schema text,
    because one guard is what keeps the two from disagreeing about which values
    a run may not put on the wire.
    """
    try:
        return str(value) if value else None
    except Exception as error:
        # The record names the failure's type and renders none of it: the value
        # that could not be read is what raised, so the exception's own text can
        # raise as readily as the read did. Interpolated, the guard raises from
        # inside its own recovery, which ends a run over a label and takes with
        # it whichever terminal was being built around the read.
        log_warning(f"AG-UI could not read {described}: {type(error).__name__}")
        return None


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
