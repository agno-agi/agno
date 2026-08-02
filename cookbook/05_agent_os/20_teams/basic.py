"""
Serve an Agent on Microsoft Teams
=================================

Mount one Agent on AgentOS's Microsoft Teams interface. The interface verifies
the inbound Bot Framework JWT, maps each Teams user to a persistent session,
and posts the Agent's response back through the Bot Connector API.

Prerequisites: OPENAI_API_KEY and the MICROSOFT_APP_* credentials in README.md
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_teams/basic.py
Try: GET http://localhost:7777/msteams/status, then message the bot from Teams
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.teams import MicrosoftTeams

# ---------------------------------------------------------------------------
# Create the Teams AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="teams-basic-db",
    db_file="tmp/teams_basic.db",
)

assistant = Agent(
    id="teams-assistant",
    name="Teams Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    instructions=[
        "You are chatting with the user on Microsoft Teams.",
        "Keep responses conversational and concise; markdown is supported.",
    ],
)

agent_os = AgentOS(
    id="teams-basic-os",
    description="A minimal AgentOS exposed through the Microsoft Teams interface.",
    agents=[assistant],
    interfaces=[MicrosoftTeams(agent=assistant)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the Teams Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
