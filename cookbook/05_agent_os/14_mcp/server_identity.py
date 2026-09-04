"""
Name, version and instructions for the MCP server
=================================================

Set what a client learns about the server when it connects. The instructions
tell the calling model what the tools are for and how to use them.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/server_identity.py
Try: open http://localhost:7777/mcp in a browser to see the server card, or connect
     an MCP client and read the initialize response
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig

# ---------------------------------------------------------------------------
# Create the agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-server-identity-db",
    db_file="tmp/mcp_server_identity.db",
)

support_agent = Agent(
    id="support-agent",
    name="Support Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions="Answer product questions clearly and concisely.",
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="mcp-server-identity-os",
    name="Support AgentOS",
    version="1.4.0",
    description="AgentOS that describes its MCP server to connecting clients.",
    db=db,
    agents=[support_agent],
    mcp=MCPConfig(
        # Defaults: the AgentOS name and AgentOS(version=...).
        name="Acme Support",
        version="1.4.0",
        instructions=(
            "This server answers questions about Acme products. Start with run_agent "
            "and the support-agent. Answer from the agent's reply and say when it "
            "does not know."
        ),
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
