"""
Google Workspace Agent with DB Token Storage + Encryption
==========================================================

Multi-toolkit agent with Gmail, Calendar, Drive, Meet, and Tasks.
Tokens are stored encrypted in PostgreSQL for persistence across restarts.

Authentication (env vars):
  GOOGLE_CLIENT_ID          - OAuth client ID
  GOOGLE_CLIENT_SECRET      - OAuth client secret

Database:
  Uses PgDb2 for token storage. Tokens persist across app restarts.

Encryption:
  Set AGNO_ENCRYPTION_KEY to encrypt tokens at rest.

First run opens browser for OAuth consent. Subsequent runs use stored token.

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_workspace_with_db.py
"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import AuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.meet import GoogleMeetTools
from agno.tools.google.tasks import GoogleTasksTools

db = PostgresDb(db_url="postgresql://agno:agno@localhost:5532/agno")

auth = AuthConfig(
    db=db,
    token_encryption_key=getenv("AGNO_ENCRYPTION_KEY"),
)

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth=auth),
        GoogleCalendarTools(auth=auth),
        GoogleDriveTools(auth=auth),
        GoogleMeetTools(auth=auth),
        GoogleTasksTools(auth=auth),
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    print("Testing with DB token storage" + (" + encryption" if getenv("AGNO_ENCRYPTION_KEY") else ""))
    print()
    agent.print_response(
        "List my recent emails, today's calendar events, and any pending tasks",
        stream=True,
    )
