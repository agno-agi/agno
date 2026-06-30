"""
Team with Client Tools
======================

Demonstrates AG-UI client_tools with a Team.
Frontend tools are defined by the AG-UI client (e.g., CopilotKit) and executed in the browser.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# DB required for client_tools resume flow
db = SqliteDb(db_file="tmp/team_client_tools.db")

assistant = Agent(
    name="assistant",
    role="UI Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You help users with UI tasks. When the user asks to change something in the UI, use the available tools.",
    markdown=True,
)

ui_team = Team(
    members=[assistant],
    name="ui_team",
    instructions="You are a UI team that helps users interact with the frontend.",
    db=db,
    show_members_responses=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    teams=[ui_team],
    interfaces=[AGUI(team=ui_team)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    Test with curl:

    curl -X POST http://localhost:9001/agui \
      -H "Content-Type: application/json" \
      -d '{
        "thread_id": "test-123",
        "run_id": "run-1",
        "messages": [{"id": "1", "role": "user", "content": "Change the background to blue"}],
        "tools": [
          {"name": "change_background", "description": "Changes the UI background color", "parameters": {"type": "object", "properties": {"color": {"type": "string"}}}}
        ],
        "context": [],
        "state": {},
        "forwarded_props": {}
      }'
    """
    agent_os.serve(app="team_with_client_tools:app", reload=True, port=9001)
