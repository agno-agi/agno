"""
MCP server exposing a tool with $defs in its inputSchema.

When an MCP tool parameter uses a nested Pydantic model, FastMCP
generates a JSON Schema with $defs (reusable type definitions) and
$ref pointers. Before PR #6085, Agno's Claude formatter dropped
$defs, leaving dangling $ref pointers that Claude couldn't resolve.

Requires `fastmcp`:
    uv pip install fastmcp

Run with:
    fastmcp run cookbook/91_tools/mcp/complex_schema/server.py
"""

from pydantic import BaseModel, Field
from fastmcp import FastMCP

mcp = FastMCP("device_telemetry")


class TimeRange(BaseModel):
    start: str = Field(description="ISO 8601 start time")
    end: str = Field(description="ISO 8601 end time")


class DeviceQuery(BaseModel):
    device_id: str = Field(description="Device identifier, e.g. sensor-42")
    time_range: TimeRange = Field(description="Time range for the query")


@mcp.tool()
def get_device_data(query: DeviceQuery) -> str:
    """Get telemetry data for a device over a time range."""
    return (
        f"Telemetry for {query.device_id} "
        f"from {query.time_range.start} to {query.time_range.end}: "
        "temp=22.5C, humidity=65%, battery=87%"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
