"""
Serve agents as MCP tools
=========================

Turn the default MCP surface off and expose agents directly: each agent in
MCPConfig(agents=[...]) becomes an MCP tool named after its id, with the
agent's own description. An MCP client sees chief and researcher -- not
run_agent(agent_id=...) -- and each call runs through the same machinery as
the default run tools (fresh session minting, scope checks, progress).

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/agents_as_tools.py
Try: connect an MCP client to http://localhost:7777/mcp and call chief
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig

# ---------------------------------------------------------------------------
# Create the agents to expose
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="mcp-agents-as-tools-db",
    db_file="tmp/mcp_agents_as_tools.db",
)

chief = Agent(
    id="chief",
    name="Chief",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    description="Answers executive questions and delegates follow-ups.",
    instructions="Answer briefly and decisively.",
    # Every exposed tool tells the client "pass session_id back to continue the
    # conversation" -- history in context is what makes that promise real.
    add_history_to_context=True,
)

researcher = Agent(
    id="researcher",
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    description="Digs into a topic and returns sourced findings.",
    instructions="Be thorough and cite what you rely on.",
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Serve the agents as the only MCP tools
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="mcp-agents-as-tools-os",
    description="AgentOS serving its agents directly as MCP tools.",
    db=db,
    agents=[chief, researcher],
    mcp=MCPConfig(
        default_tools=False,
        agents=[chief, researcher],
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Agents-as-Tools AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
