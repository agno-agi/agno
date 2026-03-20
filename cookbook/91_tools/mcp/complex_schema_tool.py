"""
Demonstrates that Claude correctly handles tool schemas with $defs/$ref.

MCP servers using nested Pydantic models produce JSON Schemas with $defs
(reusable type definitions) and $ref pointers. Before PR #6085, Agno's
format_tools_for_model() silently dropped $defs, leaving dangling $ref
pointers that Claude couldn't resolve.

This cookbook simulates what an MCP server sends by creating a Function
with a raw $defs schema (skip_entrypoint_processing=True) — the same
code path MCP tools use. No external server needed.

Run:
    .venvs/demo/bin/python cookbook/91_tools/mcp/complex_schema_tool.py
"""

import json

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.function import Function


def get_device_data(**kwargs) -> str:
    request = kwargs.get("request", {})
    if isinstance(request, dict):
        return (
            f"Telemetry for {request['device_id']} "
            f"from {request['start_time']} to {request['end_time']}: "
            "temp=22.5C, humidity=65%, battery=87%"
        )
    return f"Telemetry for device {request}: temp=22.5C"


# Raw JSON Schema with $defs — same shape FastMCP generates for nested Pydantic models
mcp_style_tool = Function(
    name="get_device_data",
    description="Get telemetry data for a device over a time range.",
    parameters={
        "type": "object",
        "properties": {
            "request": {
                "anyOf": [{"$ref": "#/$defs/DeviceQuery"}, {"type": "string"}],
                "description": "A DeviceQuery object or a plain device ID string",
            }
        },
        "required": ["request"],
        "$defs": {
            "DeviceQuery": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device ID"},
                    "start_time": {"type": "string", "description": "ISO 8601 start"},
                    "end_time": {"type": "string", "description": "ISO 8601 end"},
                },
                "required": ["device_id", "start_time", "end_time"],
            }
        },
    },
    entrypoint=get_device_data,
    skip_entrypoint_processing=True,
)

agent = Agent(
    model=Claude(id="claude-sonnet-4-6"),
    tools=[mcp_style_tool],
    markdown=True,
)

# Verify $defs made it through the formatter
tool_dict = mcp_style_tool.to_dict()
print("Tool schema $defs present:", "$defs" in tool_dict.get("parameters", {}))
print("Schema:", json.dumps(tool_dict["parameters"], indent=2))
print()

agent.print_response(
    "Get telemetry for device sensor-42 from 2024-01-01 to 2024-01-31",
    stream=True,
)
