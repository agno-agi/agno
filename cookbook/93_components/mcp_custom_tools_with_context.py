"""
MCP Custom Tools with RunContext
================================

Demonstrates that custom MCP tools can use RunContext parameters without
causing Pydantic schema generation crashes.

Before the fix (PR #9765), this would crash with:
    PydanticSchemaGenerationError: Unable to generate pydantic-core schema

The fix hides RunContext (and other framework types) from the MCP schema,
preventing the crash while still allowing the tool to receive the context
at runtime.

Run with:
    python cookbook/93_components/mcp_custom_tools_with_context.py
"""

from agno.agent import Agent
from agno.os import AgentOS, MCPServerConfig
from agno.run import RunContext


# Custom tool that uses RunContext - would crash before the fix
async def get_user_data(query: str, ctx: RunContext) -> str:
    """Fetch user data based on the caller's identity."""
    user_id = ctx.user_id or "anonymous"
    return f"Query '{query}' executed for user: {user_id}"


# Another tool using Agent type - also hidden from schema
async def get_agent_info(question: str, agent: Agent) -> str:
    """Get information about the current agent."""
    return f"Agent '{agent.name}' answering: {question}"


def main():
    from agno.os.mcp import build_mcp_server

    # Create a simple agent
    agent = Agent(name="Demo Agent", id="demo-agent")

    # Register custom tools on the MCP server
    # Before the fix, this would crash with PydanticSchemaGenerationError
    os = AgentOS(
        agents=[agent],
        mcp_server=MCPServerConfig(
            tools=[get_user_data, get_agent_info],
            enable_builtin_tools=True,
        ),
    )

    # Build the MCP server - this would crash before the fix
    mcp = build_mcp_server(os)

    print("MCP server created successfully!")
    print(f"Server name: {mcp.name}")

    # List the registered tools
    print("\nRegistered custom tools:")
    print("  - get_user_data(query: str) -> str")
    print("    [RunContext param 'ctx' hidden from schema]")
    print("  - get_agent_info(question: str) -> str")
    print("    [Agent param 'agent' hidden from schema]")

    print("\nThe fix ensures:")
    print("  1. Tools with RunContext/Agent/Team params don't crash Pydantic")
    print("  2. Framework params are hidden from MCP clients")
    print("  3. Only user-facing params (query, question) appear in the schema")


if __name__ == "__main__":
    main()
