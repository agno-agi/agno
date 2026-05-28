"""
Enterprise Google OAuth Configuration
======================================

Restricts OAuth to users from a specific Google Workspace domain.
Users with @gmail.com or other domains cannot authenticate.

When to use:
  - Internal tools that should only be accessible to company employees
  - B2B apps where you want to restrict to customer's domain

Authentication (env vars):
  GOOGLE_CLIENT_ID     - OAuth client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET - OAuth client secret

Optional (can also set via constructor):
  GOOGLE_HOSTED_DOMAIN - Restrict to this domain (e.g., "company.com")

Setup:
  1. Google Cloud Console -> OAuth consent screen -> Add your domain
  2. Create OAuth 2.0 Client ID (Desktop app for local testing)
  3. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_enterprise_oauth.py
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuthManager
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.oauth_tools import GoogleOAuthTools

# ---------------------------------------------------------------------------
# Enterprise Auth Config
# ---------------------------------------------------------------------------
# hosted_domain restricts OAuth to users from this domain only.

auth = GoogleAuthManager(
    client_id=getenv("GOOGLE_CLIENT_ID"),
    client_secret=getenv("GOOGLE_CLIENT_SECRET"),
    hosted_domain="agno.com",  # Only @agno.com users can authenticate
    store_tokens=True,
)

agent = Agent(
    name="Enterprise OAuth Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=SqliteDb(db_file="tmp/enterprise_oauth.db"),
    tools=[
        GoogleOAuthTools(auth_config=auth),
        GmailTools(
            auth_config=auth, include_tools=["get_latest_emails", "search_emails"]
        ),
        GoogleCalendarTools(
            auth_config=auth, include_tools=["list_events", "create_event"]
        ),
    ],
    instructions=(
        "You are an enterprise assistant with Gmail and Calendar access. "
        "If any Google tool returns an authentication error, call oauth_google."
    ),
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response("What tools do you have access to?")
