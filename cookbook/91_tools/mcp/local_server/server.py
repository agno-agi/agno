"""
`fastmcp` is required for this demo.

```bash
uv pip install fastmcp
```

Run this with `fastmcp run cookbook/90_tools/mcp/local_server/server.py`
"""

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


mcp = FastMCP("weather_tools")


@mcp.tool()
def get_weather(city: str) -> str:
    return f"The weather in {city} is sunny"


@mcp.tool()
def get_temperature(city: str) -> str:
    return f"The temperature in {city} is 70 degrees"


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
