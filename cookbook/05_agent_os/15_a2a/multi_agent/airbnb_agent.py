"""
Serve an Airbnb Specialist over A2A
===================================

Connect an Agent to the OpenBNB MCP server and expose it on the dedicated A2A
topology port. AgentOS manages the MCP subprocess for the server lifespan.

Prerequisites: OPENAI_API_KEY, Node.js with npx, internet access, and the `agno[a2a,mcp]` extras
Run: .venvs/demo/bin/python cookbook/05_agent_os/15_a2a/multi_agent/airbnb_agent.py
Try: Fetch GET http://127.0.0.1:7783/a2a/agents/airbnb-agent/.well-known/agent-card.json
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Airbnb Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="a2a-airbnb-db",
    db_file="tmp/a2a_airbnb.db",
)

airbnb_tools = MCPTools(
    command="npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt",
    timeout_seconds=30,
)

airbnb_agent = Agent(
    id="airbnb-agent",
    name="Airbnb Agent",
    description="An A2A specialist for Airbnb accommodation searches.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[airbnb_tools],
    instructions=[
        "Call airbnb_search exactly once to find stays that match the request.",
        "Use airbnb_listing_details only when more detail is needed.",
        "If a tool returns an error, do not retry it; report the error and search URL.",
        "Return a short shortlist with dates, prices, and listing links.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="a2a-airbnb-os",
    description="AgentOS serving the Airbnb specialist.",
    agents=[airbnb_agent],
    a2a_interface=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Airbnb AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7783)
