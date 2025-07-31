"""This example shows how to run an Agent using our MCP integration in the Agno Playground.

For this example to run you need:
- Create a GitHub personal access token following these steps:
    - https://github.com/modelcontextprotocol/servers/tree/main/src/github#setup
- Set the GITHUB_TOKEN environment variable: `export GITHUB_TOKEN=<Your GitHub access token>`
- Run: `pip install agno mcp openai` to install the dependencies
"""

from contextlib import asynccontextmanager
from os import getenv
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.mcp import MCPTools
from fastapi import FastAPI
from mcp import StdioServerParameters

agent_storage_file: str = "tmp/agents.db"


# MCP server parameters setup
github_token = getenv("GITHUB_TOKEN") or getenv("GITHUB_ACCESS_TOKEN")
if not github_token:
    raise ValueError("GITHUB_TOKEN environment variable is required")

server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-github"],
)


# This is required to start the MCP connection correctly in the FastAPI lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage MCP connection lifecycle inside a FastAPI app"""
    global mcp_tools

    # Startuplogic: connect to our MCP server
    mcp_tools = MCPTools(server_params=server_params)
    await mcp_tools.connect()

    # Add the MCP tools to our Agent
    agent.tools = [mcp_tools]

    yield

    # Shutdown: Close MCP connection
    await mcp_tools.close()


agent = Agent(
    name="MCP GitHub Agent",
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

# Setup the Playground app
playground = Playground(
    agents=[agent],
    name="MCP Demo",
    description="A playground for MCP",
    app_id="mcp-demo",
)

# Initialize the Playground app with our lifespan logic
app = playground.get_app(lifespan=lifespan)


if __name__ == "__main__":
    playground.serve(app="mcp_demo:app", reload=True)
