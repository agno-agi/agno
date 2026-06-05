"""
Google Workspace Agent with DB Token Storage
=============================================

Multi-toolkit agent with Gmail, Calendar, Drive, Meet, and Tasks.
Tokens are stored encrypted in PostgreSQL for persistence across restarts.

Authentication (env vars):
  GOOGLE_CLIENT_ID          - OAuth client ID
  GOOGLE_CLIENT_SECRET      - OAuth client secret
  GOOGLE_TOKEN_ENCRYPTION_KEY - Key for encrypting stored tokens (optional)

Database:
  Uses PgDb2 for token storage. Tokens persist across app restarts.

First run opens browser for OAuth consent. Subsequent runs use stored token.

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_workspace_with_db.py
"""

from agno.agent import Agent
from agno.db.postgres import PgDb2
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.meet import GoogleMeetTools
from agno.tools.google.tasks import GoogleTasksTools

db = PgDb2(
    host="localhost",
    port=5532,
    db="agno",
    user="agno",
    password="agno",
)

auth = GoogleAuth(db=db)

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth=auth),
        GoogleCalendarTools(auth=auth),
        GoogleDriveTools(auth=auth),
        GoogleMeetTools(),
        GoogleTasksTools(),
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "List my recent emails, today's calendar events, and any pending tasks",
        stream=True,
    )
