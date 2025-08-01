import asyncio
import sys
from pathlib import Path

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(prompt: str) -> None:
    # Initialize the MCP server
    server_params = StdioServerParameters(
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            str(Path(__file__).parent.parent),
        ],
    )
    # Create a client session to connect to the MCP server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the MCP toolkit
            mcp_tools = MCPTools(session=session)
            await mcp_tools.initialize()

            # Create an agent with the MCP toolkit
            agent = Agent(tools=[mcp_tools])

            # Run the agent
            await agent.aprint_response(prompt, stream=True)


if __name__ == "__main__":
    prompt = (
        sys.argv[1] if len(sys.argv) > 1 else "Read and summarize the file ./LICENSE"
    )
    asyncio.run(main(prompt))
