"""
Name, version and instructions for the MCP server
=================================================

An MCP client learns three things about a server when it connects: the name,
the version and the instructions. The instructions tell the calling model what
the tools are for and how to use them. Claude, Cursor and ChatGPT read them.

By default the server takes the AgentOS name and the version passed to
``AgentOS(version=...)``. ``MCPConfig`` overrides both and sets the instructions.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/server_identity.py
Try: connect an MCP client to http://localhost:7777/mcp and read the name,
     version and instructions from the initialize response
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
# Describe the server to the clients that connect to it
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="mcp-server-identity-os",
    name="Support AgentOS",
    version="1.4.0",
    description="AgentOS that describes its MCP server to connecting clients.",
    db=db,
    agents=[support_agent],
    mcp=MCPConfig(
        # Shown in the client's server list. Defaults to the AgentOS name.
        name="Acme Support",
        # Reported as serverInfo.version. Defaults to AgentOS(version=...).
        version="1.4.0",
        # Read by the calling model at connect time.
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
