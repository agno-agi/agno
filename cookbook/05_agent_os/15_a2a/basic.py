"""
Serve an Agent over A2A
=======================

Expose one persistent Agent through AgentOS's built-in A2A interface. The
`a2a_interface=True` shorthand exposes every registered entity; use an
explicit `interfaces=[A2A(agents=[...])]` when you need to select which
entities are exposed or customize interface tags.

Prerequisites: OPENAI_API_KEY and the `agno[a2a]` extra
Run: .venvs/demo/bin/python cookbook/05_agent_os/15_a2a/basic.py
Try: Run client.py, then fetch GET http://127.0.0.1:7779/a2a/agents/a2a-assistant/.well-known/agent-card.json
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="a2a-basic-db",
    db_file="tmp/a2a_basic.db",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

a2a_assistant = Agent(
    id="a2a-assistant",
    name="A2A Assistant",
    description="A concise assistant that remembers facts across A2A turns.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "Help the user through the A2A protocol.",
        "Remember facts supplied earlier in the same conversation.",
        "When asked to repeat a project code, return the code exactly.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="a2a-basic-os",
    description="A minimal AgentOS exposing one persistent A2A Agent.",
    agents=[a2a_assistant],
    a2a_interface=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7779)
