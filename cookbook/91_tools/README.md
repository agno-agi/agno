# Tools

Examples for using and creating tools in Agno.

## Tool Types

| Type | Description |
|:-----|:------------|
| **Built-in Tools** | Pre-built toolkits (YFinance, DuckDuckGo, etc.) |
| **Custom Tools** | Your own tools with @tool decorator |
| **MCP Tools** | Model Context Protocol servers |
| **Async Tools** | Async tool execution |

## Custom Tools

```python
from agno.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Weather in {city}: Sunny, 72F"

agent = Agent(tools=[get_weather])
```

## MCP Tools

Model Context Protocol allows connecting to external tool servers:

```python
from agno.tools.mcp import MCPTools

tools = MCPTools(servers=["npx", "-y", "@anthropic/mcp-server-filesystem"])
agent = Agent(tools=[tools])
```

## Folders

- `mcp/` - MCP server examples
- `tool_decorator/` - Custom tool patterns
- `tool_hooks/` - Pre/post processing
- `async/` - Async execution
