from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# Create a database for the Agent
db = SqliteDb(db_file="agno.db")

# Define the MCP server to use
agno_mcp_server = MCPTools(
    transport="streamable-http", url="https://docs-v2.agno.com/mcp"
)

# Define the Agent
agno_agent = Agent(
    name="Agno Agent",
    model=Claude(id="claude-sonnet-4-0"),
    # Add the database to the Agent
    db=db,
    # Add the MCP server to the Agent
    tools=[agno_mcp_server],
    # Add the previous session history to the context
    add_history_to_context=True,
    # Specify number of previous runs to add to the context
    num_history_runs=3,
    markdown=True,
)


# Create the AgentOS
agent_os = AgentOS(agents=[agno_agent])
# Create the FastAPI app for the AgentOS
app = agent_os.get_app()

if __name__ == "__main__":
    """Run the AgentOS."""
    agent_os.serve(app="agno_mcp:app")
