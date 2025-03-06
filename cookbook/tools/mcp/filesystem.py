"""📁 MCP Filesystem Agent - Your Personal File Explorer!

This example shows how to create a filesystem agent that uses MCP to explore,
analyze, and provide insights about files and directories. The agent leverages the Model
Context Protocol (MCP) to interact with the filesystem, allowing it to answer questions
about file contents, directory structures, and more.

Example prompts to try:
- "What files are in the current directory?"
- "Show me the content of README.md"
- "What is the license for this project?"
- "Find all Python files in the project"
- "Summarize the main functionality of the codebase"

Run: `pip install agno mcp openai` to install the dependencies
"""

import asyncio
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def create_filesystem_agent(session):
    """Create and configure a filesystem agent with MCP tools."""
    # Initialize the MCP toolkit
    mcp_tools = MCPTools(session=session)
    await mcp_tools.initialize()

    # Create an agent with the MCP toolkit
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[mcp_tools],
        instructions=dedent("""\
            You are a filesystem assistant. Help users explore files and directories.

            - Navigate the filesystem to answer questions
            - Use the list_allowed_directories tool to find directories that you can access
            - Provide clear context about files you examine
            - Use headings to organize your responses
            - Be concise and focus on relevant information\
        """),
        markdown=True,
        show_tool_calls=True,
    )


async def run_agent(message: str) -> None:
    """Run the filesystem agent with the given message."""
    # Initialize the MCP server
    server_params = StdioServerParameters(
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            str(Path(__file__).parent.parent.parent.parent),
        ],
    )

    # Create a client session to connect to the MCP server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            agent = await create_filesystem_agent(session)

            # Run the agent
            await agent.aprint_response(message, stream=True)


# Example usage
if __name__ == "__main__":
    # Basic example - exploring project license
    asyncio.run(run_agent("What is the license for this project?"))

    # File content example
    asyncio.run(
        run_agent("Show me the content of README.md and explain what this project does")
    )


# More example prompts to explore:
"""
File exploration queries:
1. "What are the main Python packages used in this project?"
2. "Show me all configuration files and explain their purpose"
3. "Find all test files and summarize what they're testing"
4. "What's the project's entry point and how does it work?"
5. "Analyze the project's dependency structure"

Code analysis queries:
1. "Explain the architecture of this codebase"
2. "What design patterns are used in this project?"
3. "Find potential security issues in the codebase"
4. "How is error handling implemented across the project?"
5. "Analyze the API endpoints in this project"

Documentation queries:
1. "Generate a summary of the project documentation"
2. "What features are documented but not implemented?"
3. "Are there any TODOs or FIXMEs in the codebase?"
4. "Create a high-level overview of the project's functionality"
5. "What's missing from the documentation?"
"""
