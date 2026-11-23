"""
Mount Multiple Slack Bots
=========================

Serve a research bot and an analysis bot from one AgentOS. Each Slack app has
its own credentials, URL prefix, identity, and entity-scoped thread sessions.

Prerequisites: RESEARCH_SLACK_TOKEN, RESEARCH_SLACK_SIGNING_SECRET, ANALYST_SLACK_TOKEN, ANALYST_SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/multiple_bots.py
Try in Slack: Ask the research bot for sources, then ask the analyst bot for a brief
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history (per app)
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.websearch import WebSearchTools


def required_env(name: str) -> str:
    value = getenv(name)
    if not value:
        raise ValueError(f"{name} is required for this example")
    return value


# ---------------------------------------------------------------------------
# Create Multi-bot Slack AgentOS
# ---------------------------------------------------------------------------

research_token = required_env("RESEARCH_SLACK_TOKEN")
research_secret = required_env("RESEARCH_SLACK_SIGNING_SECRET")
analyst_token = required_env("ANALYST_SLACK_TOKEN")
analyst_secret = required_env("ANALYST_SLACK_SIGNING_SECRET")

db = SqliteDb(
    id="slack-multiple-bots-db",
    db_file="tmp/slack_multiple_bots.db",
)

researcher = Agent(
    id="slack-research-bot",
    name="Slack Research Bot",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[WebSearchTools()],
    instructions=[
        "Research current questions and cite source links.",
        "Introduce yourself as the Research Bot.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

analyst = Agent(
    id="slack-analysis-bot",
    name="Slack Analysis Bot",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "Turn information from the user into concise findings and next steps.",
        "Introduce yourself as the Analysis Bot.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    id="slack-multiple-bots-os",
    description="AgentOS serving two separately credentialed Slack apps.",
    agents=[researcher, analyst],
    interfaces=[
        Slack(
            agent=researcher,
            prefix="/research",
            token=research_token,
            signing_secret=research_secret,
            streaming=True,
        ),
        Slack(
            agent=analyst,
            prefix="/analyst",
            token=analyst_token,
            signing_secret=analyst_secret,
            streaming=True,
        ),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Multi-bot Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
