"""
Google Service Account Authentication
======================================

Server-to-server auth without user interaction. No OAuth needed.

Setup:
  1. Google Cloud Console -> IAM & Admin -> Service Accounts -> Create
  2. Download JSON key file
  3. For Gmail: Enable domain-wide delegation in Google Workspace Admin
  4. Set env vars:
     export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json
     export GOOGLE_DELEGATED_USER=user@domain.com  # Gmail only

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_service_account.py
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools

# Configure once — auto-propagates to all Google toolkits
auth = GoogleAuthConfig(
    service_account_path=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
    delegated_user=os.getenv("GOOGLE_DELEGATED_USER"),
)

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth_config=auth),  # First toolkit gets config, others inherit
        GoogleCalendarTools(),
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"):
        print("Set GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_DELEGATED_USER env vars")
    else:
        agent.print_response("What events do I have today?", stream=True)
