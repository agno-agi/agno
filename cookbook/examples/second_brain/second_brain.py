"""
Second Brain - Memory You Own, Behind Your Own MCP Server
=========================================================
A private agent that remembers what you are building: durable notes in its own
filesystem, plus what it learns about how you work. It is also an MCP server, so
your AI apps (claude, chatgpt, claude code) can read and write the same brain.

Running this file serves the AgentOS on http://localhost:7777
MCP Server on http://localhost:7777/mcp
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# One database for agent sessions, learning, notes, traces, metrics, etc.
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/second_brain.db")
notes = FileSystem(db, namespace="brain/{user_id}")

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
second_brain = Agent(
    db=db,
    id="second-brain",
    name="Second Brain",
    model="openai:gpt-5.6",
    tools=[notes.tools()],
    instructions=[
        "You're a second brain for: {user_id}.",
        "Remember what they're building. Keep one note per project in "
        "notes/<project>.md and append decisions as they are made.",
        "Answer according to their taste. In under 3 sentences unless they ask for more.",
        notes.instructions(),
    ],
    enable_agentic_memory=True,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Create the AgentOS - API on /, MCP on /mcp
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    db=db,
    tracing=True,
    mcp_server=True,
    agents=[second_brain],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="second_brain:app", reload=True)
