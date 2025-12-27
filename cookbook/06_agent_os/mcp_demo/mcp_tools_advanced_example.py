"""
Example AgentOS app where the agent has MCPTools.

AgentOS handles the lifespan of the MCPTools internally.
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools  # noqa: F401

# Setup the database
db = SqliteDb(db_file="tmp/agentos.db")

agno_mcp_tools = MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")

# Example: Brave Search MCP server
brave_mcp_tools = MCPTools(
    command="npx -y @modelcontextprotocol/server-brave-search",
    env={
        "BRAVE_API_KEY": getenv("BRAVE_API_KEY"),
    },
    timeout_seconds=60,
)

# You can also use MultiMCPTools to connect to multiple MCP servers at once:
#
# from agno.tools.mcp import MultiMCPTools
# mcp_tools = MultiMCPTools(
#     commands=["npx -y @modelcontextprotocol/server-brave-search"],
#     urls=["https://docs.agno.com/mcp"],
#     env={"BRAVE_API_KEY": getenv("BRAVE_API_KEY")},
# )

# Setup ai framework agent
ai_framework_agent = Agent(
    id="agno-support-agent",
    name="Agno Support Agent",
    model=Claude(id="claude-sonnet-4-0"),
    db=db,
    tools=[brave_mcp_tools, agno_mcp_tools],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    description="Example app with MCP Tools",
    agents=[ai_framework_agent],
)


app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    You can see test your AgentOS at:
    http://localhost:7777/docs

    """
    # Don't use reload=True here, this can cause issues with the lifespan
    agent_os.serve(app="mcp_tools_advanced_example:app")
