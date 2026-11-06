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

## Workspace speech

`sixtydb_tools.py` uses 60db workspace voices. Set `SIXTYDB_API_KEY` and the
credentials for the agent's model. `SIXTYDB_VOICE_ID` is optional: without it,
the example calls `get_voices()` and selects the first voice in the quality
catalog. Set the voice ID explicitly to use another voice, including one from
`get_voices(model="fast")`. Voice IDs are specific to your workspace.

Run `python cookbook/91_tools/sixtydb_tools.py` from the repository root. The
example writes WAV audio to `tmp/greeting.wav`, prints the output path, and
reports when no audio is returned. Discovery and synthesis failures log
diagnostics without API keys or response bodies.

The toolkit requests mono LINEAR16 at 24 kHz and reads `audio_base64` from a
JSON object, either at the top level or under `backendResponse`. It decodes
the base64 once and removes a WAV header when present before producing an
Agno WAV audio artifact. Incompatible audio formats fail explicitly.

## Folders

- `finance/` - FinanceTools: one finance toolkit, swappable data providers (yfinance, financialdatasets.ai)
- `mcp/` - MCP server examples
- `sprites_tools/` - Run commands in a persistent Fly.io Sprite; includes a check without an LLM
- `tool_decorator/` - Custom tool patterns
- `tool_hooks/` - Pre/post processing
- `async/` - Async execution
