"""
Multiple Slack Bot Instances
============================

Deploy multiple agents as separate Slack bots in one workspace.
Each bot has its own identity, token, and signing secret.

Setup:
  1. Create two Slack apps at https://api.slack.com/apps
  2. Install both apps to the same workspace
  3. Set each app's Event Subscription URL to its prefix:
       - @ResearchBot  ->  https://myapp.com/research/events
       - @AnalystBot   ->  https://myapp.com/analyst/events
  4. Set environment variables (or pass tokens directly):
       RESEARCH_SLACK_TOKEN, RESEARCH_SLACK_SIGNING_SECRET
       ANALYST_SLACK_TOKEN,  ANALYST_SLACK_SIGNING_SECRET
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/persistent_memory.db")

research_agent = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[WebSearchTools()],
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
)

analyst_agent = Agent(
    name="Analyst Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    instructions=[
        "You are a data analyst. Help users interpret data and create insights."
    ],
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# AgentOS — each Slack interface gets its own credentials
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[research_agent, analyst_agent],
    interfaces=[
        Slack(
            agent=research_agent,
            prefix="/research",
            token=getenv("RESEARCH_SLACK_TOKEN"),
            signing_secret=getenv("RESEARCH_SLACK_SIGNING_SECRET"),
        ),
        Slack(
            agent=analyst_agent,
            prefix="/analyst",
            token=getenv("ANALYST_SLACK_TOKEN"),
            signing_secret=getenv("ANALYST_SLACK_SIGNING_SECRET"),
        ),
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="multiple_instances:app", reload=True)
