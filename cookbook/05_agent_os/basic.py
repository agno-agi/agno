"""
Hello AgentOS
=============

Serve one persistent agent as a FastAPI application. After the server starts,
open http://localhost:7777/config to inspect the API surface, then connect the
server to the AgentOS control plane at https://os.agno.com.

Prerequisites: OPENAI_API_KEY and internet access to https://docs.agno.com/mcp
Run: .venvs/demo/bin/python cookbook/05_agent_os/basic.py
Try: Open http://localhost:7777/config, then ask "How do I create an AgentOS?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="hello-agent-os-db",
    db_file="tmp/agent_os.db",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agno_assist = Agent(
    id="agno-assist",
    name="Agno Assist",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[MCPTools(url="https://docs.agno.com/mcp")],
    instructions="Answer questions about Agno using the documentation tools.",
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="hello-agent-os",
    description="A minimal AgentOS with one persistent agent.",
    agents=[agno_assist],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
