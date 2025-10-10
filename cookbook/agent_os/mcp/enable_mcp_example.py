"""
Example AgentOS app with MCP enabled.

After starting this AgentOS app, you can test the MCP server with the test_client.py file.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools

# Setup the database
db = SqliteDb(db_file="tmp/agentos.db")

# Setup basic research agent
web_research_agent = Agent(
    id="web-research-agent",
    name="Web Research Agent",
    model=Claude(id="claude-sonnet-4-0"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    enable_session_summaries=True,
    markdown=True,
)


# Setup our AgentOS with MCP enabled
agent_os = AgentOS(
    description="Example app with MCP enabled",
    agents=[web_research_agent],
    enable_mcp_server=True,  # This enables a LLM-friendly MCP server at /mcp
)

app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    You can see view your LLM-friendly MCP server at:
    http://localhost:7777/mcp

    """
    agent_os.serve(app="enable_mcp_example:app")
