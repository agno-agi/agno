"""🐙 MCP GitHub Agent - Your Personal GitHub Explorer!

This example shows how to create a GitHub agent that uses MCP to explore,
analyze, and provide insights about GitHub repositories. The agent leverages the Model
Context Protocol (MCP) to interact with GitHub, allowing it to answer questions
about issues, pull requests, repository details and more.

Example prompts to try:
- "List open issues in the repository"
- "Show me recent pull requests"
- "What are the repository statistics?"
- "Find issues labeled as bugs"
- "Show me contributor activity"

Run: `pip install agno mcp openai` to install the dependencies
Environment variables needed:
- Create a GitHub personal access token following these steps:
    - https://github.com/modelcontextprotocol/servers/tree/main/src/github#setup
- export GITHUB_TOKEN: Your GitHub personal access token
"""

import asyncio
import os
from textwrap import dedent

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters


async def run_agent(message: str) -> None:
    """Run the GitHub agent with the given message."""

    # Initialize the MCP server
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
    )

    # Create a client session to connect to the MCP server
    async with MCPTools(server_params=server_params) as mcp_tools:
        agent = Agent(
            tools=[mcp_tools],
            instructions=dedent("""\
                You are a GitHub assistant. Help users explore repositories and their activity.

                - Use headings to organize your responses
                - Be concise and focus on relevant information\
            """),
            markdown=True,
            show_tool_calls=True,
        )

        # Run the agent
        await agent.aprint_response(message, stream=True)


# Example usage
if __name__ == "__main__":
    # Pull request example
    asyncio.run(
        run_agent(
            "Tell me about Agno. Github repo: https://github.com/agno-agi/agno. You can read the README for more information."
        )
    )


# More example prompts to explore:
"""
Issue queries:
1. "Find issues needing attention"
2. "Show me issues by label"
3. "What issues are being actively discussed?"
4. "Find related issues"
5. "Analyze issue resolution patterns"

Pull request queries:
1. "What PRs need review?"
2. "Show me recent merged PRs"
3. "Find PRs with conflicts"
4. "What features are being developed?"
5. "Analyze PR review patterns"

Repository queries:
1. "Show repository health metrics"
2. "What are the contribution guidelines?"
3. "Find documentation gaps"
4. "Analyze code quality trends"
5. "Show repository activity patterns"
"""
