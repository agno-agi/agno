"""
Google Auth — Unified OAuth for multiple Google toolkits.

Demonstrates how to use GoogleAuth as a standalone toolkit alongside
Gmail and Calendar tools. When auth fails, the agent calls
authenticate_google to get the OAuth URL for the user.

Two patterns shown:
  1. Pre-loaded credentials (shared token file, auth happens once)
  2. No credentials (agent uses authenticate_google to request access)

Setup:
  export GOOGLE_CLIENT_ID=your_client_id
  export GOOGLE_CLIENT_SECRET=your_client_secret
  export GOOGLE_PROJECT_ID=your_project_id
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# GoogleAuth — register services for OAuth URL generation
# ---------------------------------------------------------------------------
google_auth = GoogleAuth()
google_auth.register_service("gmail", GmailTools.DEFAULT_SCOPES)
google_auth.register_service("calendar", GoogleCalendarTools.DEFAULT_SCOPES)

# ---------------------------------------------------------------------------
# Shared credentials (optional — load from a combined token file)
# ---------------------------------------------------------------------------
creds = None
token_path = Path("token_google.json")
if token_path.exists():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(token_path))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())

# ---------------------------------------------------------------------------
# Agent with Gmail + Calendar + GoogleAuth
# ---------------------------------------------------------------------------
agent = Agent(
    name="Google Assistant",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            creds=creds,
            send_email=False,
            send_email_reply=False,
            include_tools=["get_latest_emails", "search_emails"],
        ),
        GoogleCalendarTools(
            creds=creds,
            include_tools=["list_events", "search_events"],
        ),
        google_auth,
    ],
    instructions=[
        "You help users with their emails and calendar.",
        "If a Google tool returns an authentication error, call authenticate_google to get the OAuth URL.",
        "Send the OAuth URL to the user so they can grant access.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    # Test with shared credentials
    agent.print_response("What are my 2 latest emails?", stream=True)
    agent.print_response("What meetings do I have this week?", stream=True)
