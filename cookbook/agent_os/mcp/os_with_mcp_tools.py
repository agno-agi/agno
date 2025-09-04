"""
Example AgentOS app with MCP enabled.

After starting this AgentOS app, you can test the MCP server with the test_client.py file.
"""

from contextlib import asynccontextmanager

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.mcp import MCPTools
from fastapi import FastAPI

# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


mcp_tools = MCPTools(transport="streamable-http", url="https://docs-v2.agno.com/mcp")

# Setup basic agents, teams and workflows
agno_support_agent = Agent(
    id="agno-support-agent",
    name="Agno Support Agent",
    model=Claude(id="claude-sonnet-4-0"),
    db=db,
    tools=[mcp_tools],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)


# This is required so that the lifespan is only created once
def get_agent_os():
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Start the MCP tools
        await mcp_tools.connect()
        yield
        # Clean up the MCP tools and release the resources
        await mcp_tools.close()

    return AgentOS(
        description="Example app with MCP enabled",
        agents=[agno_support_agent],
        lifespan=lifespan,
    )


agent_os = get_agent_os()
app = agent_os.get_app()

if __name__ == "__main__":
    """Run our AgentOS.

    You can see test your AgentOS at:
    http://localhost:7777/docs

    """
    # Don't use reload=True here, this can cause issues with the lifespan
    agent_os.serve(app="os_with_mcp_tools:app")
