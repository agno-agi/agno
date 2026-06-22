"""
Google Workspace Agent
======================

Multi-toolkit agent with Gmail, Calendar, and Drive.
Uses DB-backed token storage with shared auth for scope aggregation.

Authentication (env vars):
  GOOGLE_CLIENT_ID     - OAuth client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET - OAuth client secret

First run opens browser for OAuth consent, saves token to DB.

Setup:
  1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/workspace/multi_toolkit.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import AuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

db = SqliteDb(db_file="tmp/multi_toolkit.db")
auth = AuthConfig(db=db)

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        GmailTools(auth=auth),
        GoogleCalendarTools(auth=auth),
        GoogleDriveTools(auth=auth),
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "List my recent emails and today's calendar events", stream=True
    )
