"""
Google Workspace Agent with DB Token Storage
=============================================

Gmail + Calendar + Drive with token persistence in SqliteDb. User consents
once and the token is reused on subsequent runs.

Setup:
  1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Export GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars
  4. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_workspace_with_db.py
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

agent = Agent(
    name="Google Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=SqliteDb(
        db_file="tmp/google_workspace.db",
        store_auth_tokens=True,
        encrypt_auth_tokens=False,
    ),
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
        "What are my 3 most recent emails, and do I have any meetings today?",
        stream=True,
        user_id="user-1",
    )
