"""
Tool Call Trajectories - Basic
==============================

Schema-validated (query, tool call) pairs from real agno tool schemas. The
JSON schemas are pulled straight from toolkits the framework actually runs
(CalculatorTools to be executable later, DuckDuckGoTools schema-only), a
generator agent writes candidate pairs against them, and every pair is
validated in pure code against the real schema: known tool, parseable JSON
arguments, all required params present, no unknown params, primitive types
match. Only pairs that survive become SFT rows.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agno.agent import Agent, RunOutput
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field
from rich.pretty import pprint

N_PAIRS = 8


# ---------------------------------------------------------------------------
# Real Tool Schemas
# ---------------------------------------------------------------------------
def toolkit_schemas(toolkit: Any, source: str) -> Dict[str, dict]:
    """Extract each tool's real JSON schema from an agno toolkit."""
    schemas = {}
    for name, fn in toolkit.functions.items():
        fn.process_entrypoint()  # populates fn.parameters from the signature and docstring
        schemas[name] = {
            "name": name,
            "description": fn.description,
            "parameters": fn.parameters,
            "source": source,
        }
    return schemas


SCHEMAS: Dict[str, dict] = {
    **toolkit_schemas(CalculatorTools(), "agno.tools.calculator"),
    **toolkit_schemas(DuckDuckGoTools(), "agno.tools.duckduckgo"),
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ToolCallPair(BaseModel):
    query: str = Field(
        ...,
        description="A realistic user request answerable by a single call to one of the listed tools",
    )
    tool_name: str = Field(
        ..., description="The tool to call, exactly as named in the schema list"
    )
    arguments_json: str = Field(
        ...,
        description='The call arguments as a JSON object string, for example {"a": 2, "b": 3}',
    )


class ToolCallPairs(BaseModel):
    pairs: list[ToolCallPair] = Field(
        ..., description="Candidate (query, tool call) pairs, each using a listed tool"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
generator = Agent(
    model="google:gemini-3.5-flash",
    instructions=(
        "You write function-calling SFT data. Given a list of tool JSON "
        "schemas, produce natural user queries that are each answerable by "
        "exactly one call to one of the tools, together with that call. "
        "Arguments must satisfy the tool's schema exactly: required params "
        "present, no extra params, correct primitive types. Vary the tools "
        "and the phrasing; put concrete values in every query."
    ),
    output_schema=ToolCallPairs,
)


# ---------------------------------------------------------------------------
# Validation Filter (stdlib)
# ---------------------------------------------------------------------------
def json_type_matches(expected: Optional[str], value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True  # schema declares no primitive type for this param: accept


def validate_pair(pair: ToolCallPair) -> Tuple[Optional[dict], str]:
    """Check one candidate against the real schema. Returns (arguments, reason)."""
    schema = SCHEMAS.get(pair.tool_name)
    if schema is None:
        return None, f"unknown tool '{pair.tool_name}'"
    try:
        arguments = json.loads(pair.arguments_json)
    except json.JSONDecodeError as exc:
        return None, f"arguments are not valid JSON: {exc.msg}"
    if not isinstance(arguments, dict):
        return None, "arguments are not a JSON object"
    properties = schema["parameters"].get("properties", {})
    for name in schema["parameters"].get("required", []):
        if name not in arguments:
            return None, f"missing required param '{name}'"
    for name, value in arguments.items():
        if name not in properties:
            return None, f"unknown param '{name}'"
        expected = properties[name].get("type")
        if not json_type_matches(expected, value):
            return (
                None,
                f"param '{name}' should be {expected}, got {type(value).__name__}",
            )
    return arguments, "ok"


# ---------------------------------------------------------------------------
# Run Generation
# ---------------------------------------------------------------------------
def build_prompt() -> str:
    schema_list = [
        {
            "name": s["name"],
            "description": s["description"],
            "parameters": s["parameters"],
        }
        for s in SCHEMAS.values()
    ]
    return (
        "Tool schemas:\n"
        + json.dumps(schema_list, indent=2)
        + f"\n\nWrite {N_PAIRS} (query, tool call) pairs. Cover at least five different tools."
    )


if __name__ == "__main__":
    out_dir = Path(__file__).parent / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tool_call_sft.jsonl"

    run: RunOutput = generator.run(build_prompt())
    candidates = run.content.pairs[:N_PAIRS]

    rows = []
    dropped = 0
    for pair in candidates:
        arguments, reason = validate_pair(pair)
        if arguments is None:
            dropped += 1
            print(f"dropped ({reason}): {pair.tool_name} <- {pair.query}")
            continue
        rows.append(
            {
                "query": pair.query,
                "tool_name": pair.tool_name,
                "arguments": arguments,
                "schema_source": SCHEMAS[pair.tool_name]["source"],
            }
        )

    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    pprint(rows[:3])
    kept = len(rows)
    print(f"wrote {kept} rows to {out_path}, kept {kept}, dropped {dropped}")
