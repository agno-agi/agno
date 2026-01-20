"""This example demonstrates how to add a prefix to the name of your MCP tools.
This is useful to avoid name collisions with other tools, especially when using multiple MCP servers."""

import asyncio

from agno.agent.agent import Agent
from agno.tools.mcp import MCPTools


async def run_agent():
    # Development environment tools
    dev_tools = MCPTools(
        transport="streamable-http",
        url="https://docs.agno.com/mcp",
        # By providing this tool_name_prefix, all the tool names will be prefixed with "dev_"
        tool_name_prefix="dev",
    )
    await dev_tools.connect()

    agent = Agent(tools=[dev_tools])
    await agent.aprint_response("Which tools do you have access to? List them all.")

    await dev_tools.close()


if __name__ == "__main__":
    asyncio.run(run_agent())
