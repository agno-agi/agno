"""
Example AgentOS app where the agent has MCPTools.

AgentOS handles the lifespan of the MCPTools internally.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import (  # noqa: F401
    MCPTools,
    MultiMCPTools,
    StreamableHTTPClientParams,
)

# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# server_params = [
#     StreamableHTTPClientParams(url="https://docs-v2.agno.com/mcp"),
#     StreamableHTTPClientParams(url="https://api.githubcopilot.com/mcp/"),
# ]

# mcp_tools = MultiMCPTools(server_params_list=server_params)
mcp_tools = MCPTools(transport="streamable-http", url="https://docs-v2.agno.com/mcp")
mcp_tools_2 = MCPTools(
    transport="streamable-http", url="https://api.githubcopilot.com/mcp/"
)

# Setup basic agents, teams and workflows
agno_support_agent = Agent(
    id="agno-support-agent",
    name="Agno Support Agent",
    model=Claude(id="claude-sonnet-4-0"),
    db=db,
    tools=[
        mcp_tools,
        mcp_tools_2,
    ],
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
    """Run our AgentOS.

    You can see test your AgentOS at:
    http://localhost:7777/docs

    """
    # Don't use reload=True here, this can cause issues with the lifespan
    agent_os.serve(app="mcp_tools_example:app")
