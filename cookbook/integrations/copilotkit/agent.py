"""Agno backend for CopilotKit: agent with session DB and AG-UI.

Run this server, then point a CopilotKit 1.5 frontend at it. Sessions are stored
in SQLite so loading an old session and sending a new message works without
tool_use/tool_result errors (see session_loader fix).
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools.decorator import tool

# Persist sessions so the session router can load them; tool results are
# restored when history is replayed (CopilotKit/Claude compatibility).
db = SqliteDb(
    db_file=str(Path(__file__).parent / "copilotkit_sessions.db"),
    session_table="sessions",
)


@tool(external_execution=True)
def show_in_ui(message: str) -> str:
    """Display a message in the frontend (frontend tool)."""
    return f"Displayed in UI: {message}"


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[show_in_ui],
    instructions="You are a helpful assistant. You can show messages in the UI using show_in_ui.",
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[AGUI(agent=agent)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    # Default port 8000 matches CopilotKit agno backend expectation.
    agent_os.serve(app="agent:app", port=8000, reload=True)
