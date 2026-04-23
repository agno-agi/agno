"""
Claude Agent SDK with custom MCP tools, wrapped in Agno's ClaudeAgent.

Shows how to add custom tools via in-process MCP servers — the Claude Agent SDK
pattern for user-defined tools.

Requirements:
    pip install claude-agent-sdk

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_mcp_tools.py
"""

from agno.agents.claude import ClaudeAgent

# ----- Define custom tools via MCP server -----
# The Claude Agent SDK uses MCP servers for custom tools.
# You can define in-process servers using create_sdk_mcp_server.

try:
    from claude_agent_sdk import create_sdk_mcp_server, tool

    @tool("get_weather", "Get the current weather for a city", {"city": str})
    async def get_weather(args):
        data = {
            "Paris": "18C, Sunny",
            "London": "12C, Cloudy",
            "Tokyo": "22C, Clear",
        }
        city = args.get("city", "")
        weather = data.get(city, "Unknown city")
        return {"content": [{"type": "text", "text": f"Weather in {city}: {weather}"}]}

    @tool("get_population", "Get the population of a city", {"city": str})
    async def get_population(args):
        data = {
            "Paris": "2.1 million",
            "London": "8.9 million",
            "Tokyo": "13.9 million",
        }
        city = args.get("city", "")
        pop = data.get(city, "unknown")
        return {"content": [{"type": "text", "text": f"Population of {city}: {pop}"}]}

    server = create_sdk_mcp_server(
        name="city-tools",
        version="1.0.0",
        tools=[get_weather, get_population],
    )

    # ----- Agent with custom MCP tools -----
    agent = ClaudeAgent(
        name="Claude City Agent",
        model="claude-sonnet-4-20250514",
        mcp_servers={"city-tools": server},
        allowed_tools=[
            "mcp__city-tools__get_weather",
            "mcp__city-tools__get_population",
        ],
        max_turns=5,
    )

    agent.print_response("What's the weather and population of Tokyo?", stream=True)

except ImportError:
    print("claude-agent-sdk is required: pip install claude-agent-sdk")
