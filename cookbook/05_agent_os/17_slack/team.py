"""
Serve a Support Team in Slack
=============================

Route each Slack request to a technical specialist or a documentation
specialist that can search current workspace discussions.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/team.py
Try in Slack: Ask "How should I debug our API timeout, and has the team discussed it?"
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, search:read.public, search:read.files, search:read.users
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools.slack import SlackTools
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Support Team Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-support-team-db",
    db_file="tmp/slack_support_team.db",
)

technical_specialist = Agent(
    id="slack-technical-specialist",
    name="Technical Specialist",
    role="Diagnose code, API, and infrastructure problems.",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[WebSearchTools()],
    instructions=[
        "Diagnose the likely cause before proposing changes.",
        "Use current primary documentation when external facts matter.",
    ],
    markdown=True,
)

documentation_specialist = Agent(
    id="slack-documentation-specialist",
    name="Documentation Specialist",
    role="Find relevant workspace discussions and explain existing guidance.",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        SlackTools(
            enable_send_message=False,
            enable_send_message_thread=False,
            enable_list_channels=False,
            enable_get_channel_history=False,
            enable_upload_file=False,
            enable_download_file=False,
            enable_search_workspace=True,
        )
    ],
    instructions=[
        "Search the Slack workspace for prior decisions and related incidents.",
        "Summarize what was decided and link the evidence returned by the tool.",
    ],
    markdown=True,
)

support_team = Team(
    id="slack-support-team",
    name="Slack Support Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[technical_specialist, documentation_specialist],
    db=db,
    instructions=[
        "Delegate debugging to the Technical Specialist.",
        "Delegate questions about prior team context to the Documentation Specialist.",
        "Use both members when a request needs diagnosis and workspace history.",
        "Return one concise, actionable response.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    id="slack-team-os",
    description="AgentOS serving a specialist support Team through Slack.",
    teams=[support_team],
    interfaces=[Slack(team=support_team)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Support Team Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
