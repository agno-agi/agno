"""Dynamic Tool Discovery for MCP

Demonstrates lazy tool loading with MCPTools. When lazy_load_tools=True,
the agent starts with only a search_tools function and discovers specific
tools on-demand based on the current task.

This reduces context consumption, improves reasoning, and enables
scalability for large tool ecosystems.

Uses:
    - OpenRouter with qwen/qwen3-32b for LLM inference
    - @modelcontextprotocol/server-filesystem as the MCP server

Requirements:
    pip install agno mcp openai
    npx (Node.js must be installed)
    OPENROUTER_API_KEY environment variable

Run:
    python cookbook/91_tools/mcp/dynamic_tool_discovery.py
"""

import asyncio
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from agno.tools.mcp import MCPTools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_agent(message: str) -> None:
    """Run the filesystem agent with lazy tool loading.

    The flow works in two phases:
    1. Discovery: Agent calls search_tools to find relevant tools.
       search_tools has stop_after_tool_call=True, so the run pauses
       after discovery, giving the agent the tool results.
    2. Execution: Agent is called again with the same message. This time,
       the discovered tools are already registered, so the agent can use them.
    """
    project_root = str(Path(__file__).parent.parent.parent.parent.resolve())

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", project_root],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            mcp_tools = MCPTools(
                session=session,
                lazy_load_tools=True,
                max_discovered_tools=5,
            )
            await mcp_tools.initialize()

            agent = Agent(
                model=OpenRouter(id="qwen/qwen3-32b"),
                tools=[mcp_tools],
                instructions=dedent("""\
                    You are a filesystem assistant with dynamic tool discovery.

                    You start with only search_tools available.
                    Use search_tools first to discover the right tools for the task.\
                """),
                markdown=True,
            )

            # Phase 1: Discovery - agent calls search_tools, run pauses
            print("--- Phase 1: Tool Discovery ---")
            discovery_response = await agent.arun(message)
            print(discovery_response.content)

            # Phase 2: Execution - agent now has discovered tools available
            print("\n--- Phase 2: Tool Execution ---")
            await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    new_query = "Please read the contents of the README.md file in the current directory and tell me what the first paragraph says."
    asyncio.run(run_agent(new_query))
