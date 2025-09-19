"""
Example AgentOS app where the agent has MCPTools.

AgentOS handles the lifespan of the MCPTools internally.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# Setup the database
db = SqliteDb(db_file="tmp/agentos.db")

mcp_tools = MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")

# Setup basic agent
agno_support_agent = Agent(
    id="agno-support-agent",
    name="Agno Support Agent",
    model=Claude(id="claude-sonnet-4-0"),
    db=db,
    tools=[mcp_tools],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)


agent_os = AgentOS(
    description="Example app with MCP Tools",
    agents=[agno_support_agent],
)


app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    You can see test your AgentOS at:
    http://localhost:7777/docs

    """
    # Don't use reload=True here, this can cause issues with the lifespan
    agent_os.serve(app="mcp_tools_example:app")
