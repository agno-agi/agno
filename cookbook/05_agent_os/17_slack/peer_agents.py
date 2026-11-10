"""
Let One Slack App Address Another
=================================

Use two Slack apps in one workspace for one-way delegation. The coordinator
ignores bot messages; only the researcher opts in with respond_to_other_apps.

Prerequisites: COORDINATOR_SLACK_TOKEN, COORDINATOR_SLACK_SIGNING_SECRET, RESEARCHER_SLACK_TOKEN, RESEARCHER_SLACK_SIGNING_SECRET, RESEARCHER_SLACK_USER_ID, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/peer_agents.py
Try in Slack: Ask the coordinator to delegate a current research question
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history (per app)
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.slack import SlackTools
from agno.tools.websearch import WebSearchTools


def required_env(name: str) -> str:
    value = getenv(name)
    if not value:
        raise ValueError(f"{name} is required for this example")
    return value


# ---------------------------------------------------------------------------
# Create Peer-app Slack AgentOS
# ---------------------------------------------------------------------------

coordinator_token = required_env("COORDINATOR_SLACK_TOKEN")
coordinator_secret = required_env("COORDINATOR_SLACK_SIGNING_SECRET")
researcher_token = required_env("RESEARCHER_SLACK_TOKEN")
researcher_secret = required_env("RESEARCHER_SLACK_SIGNING_SECRET")
researcher_user_id = required_env("RESEARCHER_SLACK_USER_ID")

db = SqliteDb(
    id="slack-peer-agents-db",
    db_file="tmp/slack_peer_agents.db",
)

coordinator = Agent(
    id="slack-peer-coordinator",
    name="Slack Peer Coordinator",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[
        SlackTools(
            token=coordinator_token,
            enable_send_message=True,
            enable_send_message_thread=True,
            enable_list_channels=False,
            enable_get_channel_history=False,
            enable_upload_file=False,
            enable_download_file=False,
        )
    ],
    instructions=[
        "Answer normal project questions directly.",
        "For research-heavy work, use send_message_thread in the current Slack thread.",
        f"Address the Researcher with the real Slack mention <@{researcher_user_id}>.",
        "Include a self-contained research request after the mention.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

researcher = Agent(
    id="slack-peer-researcher",
    name="Slack Peer Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[WebSearchTools()],
    instructions=[
        "You are the research specialist for another Slack app.",
        "When the coordinator mentions you, research the request and cite sources.",
        "Answer the human-readable thread without mentioning the coordinator again.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    id="slack-peer-agents-os",
    description="AgentOS serving an asymmetric pair of peer Slack apps.",
    agents=[coordinator, researcher],
    interfaces=[
        Slack(
            agent=coordinator,
            prefix="/coordinator",
            token=coordinator_token,
            signing_secret=coordinator_secret,
            respond_to_other_apps=False,
        ),
        Slack(
            agent=researcher,
            prefix="/researcher",
            token=researcher_token,
            signing_secret=researcher_secret,
            respond_to_other_apps=True,
        ),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Peer-app Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
