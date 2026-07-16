from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from agno.utils.json_schema import get_json_schema, get_json_schema_for_arg


# With `from __future__ import annotations` active for this module, every field's
# `.type` is stored as a string ("int") rather than a type object, which used to
# crash json_schema's dataclass branch on `str.__name__`.
@dataclass
class Point:
    x: int
    y: Optional[str]
    tags: List[int]


def test_dataclass_arg_under_future_annotations():
    schema = get_json_schema_for_arg(Point)

    assert schema["type"] == "object"
    assert schema["properties"]["x"] == {"type": "integer"}
    assert schema["properties"]["y"]["type"] == "string"
    assert schema["properties"]["tags"] == {"type": "array", "items": {"type": "integer"}}
    # x and tags are required; the Optional field is not.
    assert set(schema["required"]) == {"x", "tags"}


def test_dataclass_tool_param_schema_not_silently_dropped():
    # The realistic failure was silent: the crash was swallowed per-arg and the
    # parameter vanished from `properties` while staying in `required`.
    schema = get_json_schema({"target": Point})

    target = schema["properties"]["target"]
    assert target["type"] == "object"
    assert set(target["properties"]) == {"x", "y", "tags"}
