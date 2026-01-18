import asyncio
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.mcp import MCPTools


async def run_agent(message: str) -> None:
    file_path = str(Path(__file__).parents[3] / "libs/agno")

    # Initialize the MCP server
    async with (
        MCPTools(
            f"npx -y @modelcontextprotocol/server-filesystem {file_path}",
            include_tools=[
                "list_allowed_directories",
                "list_directory",
                "read_file",
            ],
        ) as fs_tools,
    ):
        agent = Agent(
            model=Groq(id="llama-3.3-70b-versatile"),
            tools=[fs_tools],
            instructions=dedent("""\
                - First, ALWAYS use the list_allowed_directories tool to find directories that you can access
                - Use the list_directory tool to list the contents of a directory
                - Use the read_file tool to read the contents of a file
                - Be concise and focus on relevant information\
            """),
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


# Example usage
if __name__ == "__main__":
    asyncio.run(run_agent("What is the license for this project?"))
