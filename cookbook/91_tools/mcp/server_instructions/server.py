"""
MCP server that declares usage instructions
=============================

`fastmcp` is required for this demo.

```bash
uv pip install fastmcp
```

Started over stdio by `client.py` with `python cookbook/91_tools/mcp/server_instructions/server.py`

The `instructions` passed to FastMCP travel to the client in the MCP handshake.
MCPTools adopts them as toolkit instructions, so the agent is told how to combine
the tools without the user writing that guidance into the agent themselves.
"""

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Create Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "forecast_tools",
    instructions=(
        "Forecasts are keyed by station code, not by city name. "
        "Always call lookup_station first and pass the returned code to get_forecast. "
        "Never guess a station code."
    ),
)

STATIONS = {
    "san francisco": "KSFO",
    "new york": "KJFK",
    "london": "EGLL",
}

FORECASTS = {
    "KSFO": "Fog in the morning, clearing to 65F by afternoon.",
    "KJFK": "Scattered showers, high of 58F.",
    "EGLL": "Overcast, light drizzle, high of 54F.",
}


@mcp.tool()
def lookup_station(city: str) -> str:
    """Return the station code for a city."""
    code = STATIONS.get(city.strip().lower())
    if code is None:
        return f"No station found for {city}"
    return code


@mcp.tool()
def get_forecast(station_code: str) -> str:
    """Return the forecast for a station code."""
    return FORECASTS.get(station_code.upper(), f"Unknown station code {station_code}")


# ---------------------------------------------------------------------------
# Run Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
