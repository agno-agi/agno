"""
Google Service Account Authentication
======================================

Server-to-server auth without user interaction. No OAuth consent flow needed.
Ideal for backend services, cron jobs, or multi-tenant apps.

When to use Service Account vs OAuth:
  - Service Account: Your server accesses Google APIs on behalf of users
  - OAuth: Users grant access to their own Google data interactively

Authentication (env vars):
  GOOGLE_SERVICE_ACCOUNT_FILE - Path to service account JSON key file
  GOOGLE_DELEGATED_USER       - Email of user to impersonate (required for Gmail)

Setup:
  1. Google Cloud Console -> IAM & Admin -> Service Accounts -> Create
  2. Download JSON key file
  3. For Gmail: Enable domain-wide delegation in Google Workspace Admin
     (Admin Console -> Security -> API Controls -> Domain-wide Delegation)
  4. Set GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_DELEGATED_USER env vars

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_service_account.py
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuthManager
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.sheets import GoogleSheetsTools

# ---------------------------------------------------------------------------
# Service Account Auth Config
# ---------------------------------------------------------------------------
# No OAuth consent needed — credentials come from the JSON key file.

auth = GoogleAuthManager(
    service_account_path=getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
    delegated_user=getenv("GOOGLE_DELEGATED_USER"),
)

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth_config=auth),
        GoogleCalendarTools(auth_config=auth),
        GoogleDriveTools(auth_config=auth),
        GoogleSheetsTools(auth_config=auth),
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    if not getenv("GOOGLE_SERVICE_ACCOUNT_FILE"):
        print("Set GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_DELEGATED_USER env vars")
    else:
        agent.print_response(
            "List my recent emails and today's calendar events", stream=True
        )
