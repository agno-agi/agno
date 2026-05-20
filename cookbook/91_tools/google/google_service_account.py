"""
Google Service Account Authentication
======================================

Service accounts enable server-to-server authentication without user interaction.
Ideal for bots, background jobs, and enterprise deployments.

Two modes:
1. Direct access — Service account accesses its own resources (Calendar, Drive)
2. Domain-wide delegation — Service account impersonates users (required for Gmail)

Setup for Direct Access (Calendar, Drive):
  1. Google Cloud Console -> IAM & Admin -> Service Accounts -> Create
  2. Download JSON key file
  3. Share resources with the service account email
  4. Export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json

Setup for Domain-Wide Delegation (Gmail):
  1. Create service account with domain-wide delegation enabled
  2. Google Workspace Admin -> Security -> API Controls -> Domain-wide Delegation
  3. Add client ID with required scopes
  4. Export GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_DELEGATED_USER env vars

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_service_account.py
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools

# Configure service account ONCE — auto-propagates to all Google toolkits
service_account_config = GoogleAuthConfig(
    service_account_path=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
    delegated_user=os.getenv("GOOGLE_DELEGATED_USER"),
)

# Calendar only (no delegation needed)
calendar_agent = Agent(
    name="Calendar Service Account Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GoogleCalendarTools(auth_config=service_account_config),
    ],
    instructions="You have Calendar access via service account. Only shared calendars are visible.",
    add_datetime_to_context=True,
    markdown=True,
)

# Gmail requires domain-wide delegation
gmail_agent = Agent(
    name="Gmail Service Account Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth_config=service_account_config, include_tools=["get_latest_emails", "search_emails"]),
    ],
    instructions="You have Gmail access via service account with domain-wide delegation.",
    markdown=True,
)

# Multiple toolkits — pass auth_config to first, others auto-inherit
workspace_agent = Agent(
    name="Workspace Service Account Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(auth_config=service_account_config, include_tools=["get_latest_emails", "search_emails"]),
        GoogleCalendarTools(include_tools=["list_events", "get_event", "create_event"]),
    ],
    instructions="You are a workspace assistant with Gmail and Calendar via service account.",
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    delegated_user = os.getenv("GOOGLE_DELEGATED_USER")

    if not sa_file:
        print("Service Account Demo")
        print("=" * 50)
        print("Set environment variables:")
        print("  export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json")
        print("  export GOOGLE_DELEGATED_USER=user@domain.com  # For Gmail")
    elif delegated_user:
        print(f"Testing Gmail with delegation to {delegated_user}")
        gmail_agent.print_response("Get my latest 3 emails", stream=True)
    else:
        print("Testing Calendar (no delegation)")
        calendar_agent.print_response("What events do I have today?", stream=True)
