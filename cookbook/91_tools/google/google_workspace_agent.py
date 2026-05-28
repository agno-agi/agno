"""
Google Workspace Agent (Gmail + Calendar + Drive)
=================================================

Multi-toolkit agent with Gmail, Calendar, and Drive. Uses shared GoogleAuthManager
so all three APIs are authorized in ONE OAuth consent flow.

Why GoogleAuthManager?
  When using multiple Google toolkits, each needs different OAuth scopes.
  GoogleAuthManager consolidates them into a single consent screen.
  Without it, you'd get separate OAuth prompts for each toolkit.

Authentication (env vars):
  GOOGLE_CLIENT_ID     - OAuth client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET - OAuth client secret

  First run opens browser for OAuth consent, saves token to token.json.

Setup:
  1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars
  4. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_workspace_agent.py
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuthManager
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Shared Auth Config
# ---------------------------------------------------------------------------
# Pass the same instance to all Google toolkits for combined OAuth consent.

auth = GoogleAuthManager(
    client_id=getenv("GOOGLE_CLIENT_ID"),
    client_secret=getenv("GOOGLE_CLIENT_SECRET"),
)

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(
            auth_config=auth,
            include_tools=["get_latest_emails", "search_emails", "create_draft_email"],
        ),
        GoogleCalendarTools(
            auth_config=auth,
            create_event=False,
            update_event=False,
            delete_event=False,
        ),
        GoogleDriveTools(
            auth_config=auth,
            include_tools=["list_files", "search_files", "read_file"],
        ),
    ],
    instructions=(
        "You are a Google Workspace assistant with Gmail, Calendar, and Drive access. "
        "Summarize findings clearly and concisely."
    ),
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "What are my 3 most recent emails and do I have any meetings today?",
        stream=True,
    )
