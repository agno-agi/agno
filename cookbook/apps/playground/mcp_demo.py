import asyncio
from os import getenv
from textwrap import dedent

import nest_asyncio
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

# Allow nested event loops
nest_asyncio.apply()

agent_storage_file: str = "tmp/agents.db"


async def run_server() -> None:
    """Run the GitHub agent server."""
    github_token = getenv("GITHUB_TOKEN") or getenv("GITHUB_ACCESS_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable is required")

    # Initialize the MCP server
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
    )

    # Create a client session to connect to the MCP server
    async with MCPTools(server_params=server_params) as mcp_tools:
        agent = Agent(
            name="MCP GitHub Agent",
            tools=[mcp_tools],
            instructions=dedent("""\
                You are a GitHub assistant. Help users explore repositories and their activity.

                - Use headings to organize your responses
                - Be concise and focus on relevant information\
            """),
            model=OpenAIChat(id="gpt-4o"),
            storage=SqliteAgentStorage(
                table_name="basic_agent",
                db_file=agent_storage_file,
                auto_upgrade_schema=True,
            ),
            add_history_to_messages=True,
            num_history_responses=3,
            add_datetime_to_instructions=True,
            markdown=True,
        )

        playground = Playground(agents=[agent])
        app = playground.get_app()

        # Serve the app while keeping the MCPTools context manager alive
        serve_playground_app(app)


if __name__ == "__main__":
    asyncio.run(run_server())

# Example prompts to explore:
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
