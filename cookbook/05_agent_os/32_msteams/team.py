"""
Serve a Support Team on Microsoft Teams
=======================================

Route requests to a technical specialist and a communications specialist.
Prerequisites: OPENAI_API_KEY and the MICROSOFT_APP_* credentials in README.md
Run: python cookbook/05_agent_os/32_msteams/team.py
Try: Ask for a troubleshooting checklist and a short customer update.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.msteams import MSTeams
from agno.team import Team

technical_specialist = Agent(
    name="Technical Specialist",
    role="Diagnose technical issues and suggest troubleshooting steps.",
    model=OpenAIResponses(id="gpt-5.5"),
)
communications_specialist = Agent(
    name="Communications Specialist",
    role="Turn technical findings into clear customer updates.",
    model=OpenAIResponses(id="gpt-5.5"),
)
support_team = Team(
    id="msteams-support-team",
    name="Teams Support Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[technical_specialist, communications_specialist],
    db=SqliteDb(id="msteams-team-db", db_file="tmp/msteams_team.db"),
    add_history_to_context=True,
    num_history_runs=3,
    instructions="Delegate to the relevant specialists and return one concise response.",
)
agent_os = AgentOS(
    id="msteams-team-os",
    teams=[support_team],
    interfaces=[MSTeams(team=support_team)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app)
