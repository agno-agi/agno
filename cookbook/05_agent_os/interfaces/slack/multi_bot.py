"""
Multi-Bot Streaming Test
========================

Two agents on the same Slack workspace, mounted on different prefixes.
Both use streaming mode. Tests session isolation: each bot gets its own
DB session even when responding in the same thread.

Setup:
  1. Two Slack apps (Ace + Dash) installed to the same workspace
  2. Event Subscription URLs:
       Ace  -> https://<tunnel>/ace/events
       Dash -> https://<tunnel>/slack/events
  3. Environment variables:
       ACE_SLACK_TOKEN,  ACE_SLACK_SIGNING_SECRET
       DASH_SLACK_TOKEN, DASH_SLACK_SIGNING_SECRET
  4. ngrok: ngrok http --domain=<your-subdomain>.ngrok-free.dev 7777

Slack scopes (per app): app_mentions:read, assistant:write, chat:write, im:history
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack

db = SqliteDb(session_table="agent_sessions", db_file="tmp/multi_bot.db")

ace_agent = Agent(
    id="ace",
    name="Ace",
    model=OpenAIChat(id="gpt-4.1-mini"),
    db=db,
    instructions=[
        "You are Ace, a research assistant. Always introduce yourself as Ace.",
        "When answering, cite sources and be thorough.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

dash_agent = Agent(
    id="dash",
    name="Dash",
    model=OpenAIChat(id="gpt-4.1-mini"),
    db=db,
    instructions=[
        "You are Dash, a concise summarizer. Always introduce yourself as Dash.",
        "Keep answers concise - 2-3 sentences max.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

agent_os = AgentOS(
    agents=[ace_agent, dash_agent],
    interfaces=[
        Slack(
            agent=ace_agent,
            prefix="/ace",
            token=getenv("ACE_SLACK_TOKEN"),
            signing_secret=getenv("ACE_SLACK_SIGNING_SECRET"),
            streaming=True,
            reply_to_mentions_only=False,
        ),
        Slack(
            agent=dash_agent,
            prefix="/slack",
            token=getenv("DASH_SLACK_TOKEN"),
            signing_secret=getenv("DASH_SLACK_SIGNING_SECRET"),
            streaming=True,
            reply_to_mentions_only=False,
        ),
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="multi_bot:app", reload=True)
