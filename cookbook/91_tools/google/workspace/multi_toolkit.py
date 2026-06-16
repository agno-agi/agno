"""
Google Workspace Agent (Simple OAuth)
=====================================

Multi-toolkit agent with Gmail, Calendar, and Drive.
Uses file-based token storage (token.json) for single-user local development.

Authentication (env vars):
  GOOGLE_CLIENT_ID     - OAuth client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET - OAuth client secret

First run opens browser for OAuth consent, saves token to token.json.

Setup:
  1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_workspace_simple.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(),
        GoogleCalendarTools(),
        GoogleDriveTools(),
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "List my recent emails and today's calendar events", stream=True
    )
