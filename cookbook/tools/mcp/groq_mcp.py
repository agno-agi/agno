"""📁 Groq + MCP = Lightning Fast Agents

This example demonstrates how to create a high-performance filesystem agent by combining
Groq's fast LLM inference with the Model Context Protocol (MCP). This combination delivers
exceptional speed while maintaining powerful filesystem exploration capabilities.

Example prompts to try:
- "What files are in the current directory?"
- "Show me the content of README.md"
- "What is the license for this project?"
- "Find all Python files in the project"
- "Analyze the performance benefits of using Groq with MCP"

Run: `pip install agno mcp openai` to install the dependencies
"""

import asyncio
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.mcp import MCPTools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def create_filesystem_agent(session):
    """Create and configure a high-performance filesystem agent with Groq and MCP."""
    # Initialize the MCP toolkit
    mcp_tools = MCPTools(session=session)
    await mcp_tools.initialize()

    # Create an agent with the MCP toolkit and Groq's fast LLM
    return Agent(
        model=Groq(id="llama-3.3-70b-versatile"),
        tools=[mcp_tools],
        instructions=dedent("""\
            You are a high-performance filesystem assistant powered by Groq and MCP.
            Your combination of Groq's fast inference and MCP's efficient context handling
            makes you exceptionally quick at exploring and analyzing files.

            - Navigate the filesystem with lightning speed to answer questions
            - Use the list_allowed_directories tool to find directories that you can access
            - Highlight the performance benefits of the Groq+MCP combination when relevant
            - Provide clear context about files you examine
            - Use headings to organize your responses
            - Be concise and focus on relevant information\
        """),
        markdown=True,
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

    # Performance demonstration example
    asyncio.run(
        run_agent(
            "Show me the README.md and explain how Groq with MCP enables fast file analysis"
        )
    )


# More example prompts to explore:
"""
Performance-focused queries:
1. "Analyze a large Python file and explain how Groq+MCP makes this fast"
2. "Compare the directory structure and explain how MCP efficiently provides this information"
3. "Find all TODO comments in the codebase and demonstrate the speed advantage"
4. "Process multiple configuration files simultaneously and explain the performance benefits"
5. "Explain how the Groq+MCP combination optimizes context handling for large codebases"

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
"""
