"""
Google Workspace Agent — Without GoogleAuthConfig (BROKEN)
==========================================================

WARNING: This example shows what goes WRONG without GoogleAuthConfig.

The problem:
  - Each toolkit triggers its own OAuth independently
  - First toolkit (Gmail) saves token.json with only Gmail scopes
  - Second toolkit (Calendar) reuses that token but needs Calendar scopes
  - Result: Calendar fails with "insufficient authentication scopes"

The fix:
  Use GoogleAuthConfig to consolidate all scopes into ONE OAuth consent.
  See google_workspace_agent.py for the correct pattern:

    auth = GoogleAuthConfig(
        client_id=getenv("GOOGLE_CLIENT_ID"),
        client_secret=getenv("GOOGLE_CLIENT_SECRET"),
    )
    GmailTools(auth_config=auth)
    GoogleCalendarTools(auth_config=auth)

Authentication (env vars):
  GOOGLE_CLIENT_ID     - OAuth client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET - OAuth client secret

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_workspace_no_config.py

Expected output:
  - Gmail works (token has Gmail scopes from first OAuth)
  - Calendar fails with 403 (token missing Calendar scopes)
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Multi-toolkit WITHOUT GoogleAuthConfig (BROKEN — demonstrates the problem)
# ---------------------------------------------------------------------------
# Each toolkit reads from env vars, but they don't coordinate scopes.
# First toolkit's OAuth saves token.json with only its scopes.
# Other toolkits fail because token is missing their scopes.
#
# FIX: Use GoogleAuthConfig — see google_workspace_agent.py

agent = Agent(
    name="Workspace Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(include_tools=["get_latest_emails", "search_emails"]),
        GoogleCalendarTools(create_event=False, update_event=False, delete_event=False),
        GoogleDriveTools(include_tools=["list_files", "search_files"]),
    ],
    instructions="You are a Google Workspace assistant with Gmail, Calendar, and Drive access.",
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "What are my 3 most recent emails and do I have any meetings today?",
        stream=True,
    )
