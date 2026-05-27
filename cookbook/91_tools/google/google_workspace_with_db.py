"""
Google Workspace Agent with DB Token Storage
=============================================

Multi-toolkit agent with token persistence in SqliteDb. User consents once
and the token is reused on subsequent runs — no re-auth needed.

Why DB storage?
  - File-based token.json works for single user, but doesn't scale
  - DB storage enables multi-user apps where each user has their own token
  - Token keyed by user_id — pass user_id= to agent.print_response()

Authentication (env vars):
  GOOGLE_CLIENT_ID     - OAuth client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET - OAuth client secret

Setup:
  1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars
  4. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_workspace_with_db.py
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.google.auth import GoogleAuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Database for Token Storage
# ---------------------------------------------------------------------------
# store_auth_tokens=True enables the auth_tokens table
# encrypt_auth_tokens=True would encrypt tokens at rest (recommended for prod)

db = SqliteDb(
    db_file="tmp/google_workspace.db",
    store_auth_tokens=True,
    encrypt_auth_tokens=False,
)

# ---------------------------------------------------------------------------
# Shared Auth Config
# ---------------------------------------------------------------------------
# Pass the same instance to all Google toolkits for combined OAuth consent.

auth = GoogleAuthConfig(
    client_id=getenv("GOOGLE_CLIENT_ID"),
    client_secret=getenv("GOOGLE_CLIENT_SECRET"),
)

agent = Agent(
    name="Google Workspace Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[
        GmailTools(
            auth_config=auth, include_tools=["get_latest_emails", "search_emails"]
        ),
        GoogleCalendarTools(
            auth_config=auth, create_event=False, update_event=False, delete_event=False
        ),
        GoogleDriveTools(
            auth_config=auth, include_tools=["list_files", "search_files"]
        ),
    ],
    instructions="You are a Google Workspace assistant with Gmail, Calendar, and Drive access.",
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "What are my 3 most recent emails, and do I have any meetings today?",
        stream=True,
        user_id="user-1",
    )
