"""
Google Workspace Agent
======================

Multi-toolkit agent with Gmail, Calendar, and Drive.
Uses DB-backed token storage with shared auth for scope aggregation.

Setup:
  1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Set env vars:
     - GOOGLE_CLIENT_ID
     - GOOGLE_CLIENT_SECRET
     - GOOGLE_TOKEN_ENCRYPTION_KEY (generate with: python -c "from agno.utils.encryption import generate_encryption_key; print(generate_encryption_key())")

First run opens browser for OAuth consent, saves encrypted token to DB.
Subsequent runs load the encrypted token — no re-auth needed.

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
from agno.utils.encryption import generate_encryption_key  # noqa: F401

# Token encryption: set GOOGLE_TOKEN_ENCRYPTION_KEY env var (recommended)
# Or pass explicitly: AuthConfig(db=db, token_encryption_key=generate_encryption_key())
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
