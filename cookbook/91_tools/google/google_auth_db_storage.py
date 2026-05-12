"""
Gmail Agent with DB Token Storage (Modern Pattern)
===================================================

Single-toolkit agent with token persistence in SqliteDb. First run opens
browser for OAuth consent. Token saved to DB, reused on subsequent runs.

For multi-user Slack/AgentOS deployments, see:
  cookbook/05_agent_os/interfaces/slack/gmail_oauth.py

Setup:
  1. Enable Gmail API at https://console.cloud.google.com
  2. Export GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars
  3. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_auth_db_storage.py
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.gmail import GmailTools

agent = Agent(
    name="Gmail Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=SqliteDb(db_file="tmp/google_auth.db"),
    tools=[GmailTools(include_tools=["get_latest_emails", "search_emails"])],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response("List my 3 most recent emails", stream=True, user_id="user-1")
