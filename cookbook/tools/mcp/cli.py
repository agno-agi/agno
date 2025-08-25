"""Show how to run an interactive CLI to interact with an agent equipped with MCP tools.

This example uses the MCP GitHub Agent. Example prompts to try:
- "List open issues in the repository"
- "Show me recent pull requests"
- "What are the repository statistics?"
- "Find issues labeled as bugs"
- "Show me contributor activity"

Run: `pip install agno mcp openai` to install the dependencies
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.tools.mcp import MCPTools


async def run_agent(message: str) -> None:
    """Run an interactive CLI for the GitHub agent with the given message."""

    # Create a client session to connect to the MCP server
    async with MCPTools("npx -y @modelcontextprotocol/server-github") as mcp_tools:
        agent = Agent(
            tools=[mcp_tools],
            instructions=dedent("""\
                You are a GitHub assistant. Help users explore repositories and their activity.

                - Use headings to organize your responses
                - Be concise and focus on relevant information\
            """),
            markdown=True,
        )

        # Run an interactive command-line interface to interact with the agent.
        await agent.acli_app(input=message, stream=True)


if __name__ == "__main__":
    # Pull request example
    asyncio.run(
        run_agent(
            "Tell me about Agno. Github repo: https://github.com/agno-agi/agno. You can read the README for more information."
        )
    )
