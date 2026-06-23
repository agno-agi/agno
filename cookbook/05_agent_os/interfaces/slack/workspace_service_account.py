"""
Slack + Google Service Account (Shared Credentials)
====================================================

Slack bot where ALL users share access to ONE Google Workspace account.
Uses service account authentication — no per-user OAuth needed.

Use case: Team assistant that reads a shared inbox, team calendar, or
company Drive folder. Every Slack user sees the same Google data.

When to use this vs per-user OAuth:
  - Service Account: Shared team inbox, company calendar, central docs
  - Per-user OAuth: Each user connects their own Google account

Setup:
  1. Google Cloud Console -> IAM & Admin -> Service Accounts -> Create
  2. Download JSON key file
  3. Enable domain-wide delegation in Google Workspace Admin:
       Admin Console -> Security -> API Controls -> Domain-wide Delegation
       Add the service account client ID with scopes:
         - https://www.googleapis.com/auth/gmail.readonly
         - https://www.googleapis.com/auth/calendar.readonly
         - https://www.googleapis.com/auth/drive.readonly
  4. Slack App -> Event Subscriptions:
       https://<your-domain>/slack/events
  5. Env vars:
       SLACK_TOKEN, SLACK_SIGNING_SECRET
       GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service_account.json
       GOOGLE_DELEGATED_USER=shared-inbox@yourcompany.com

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/workspace_service_account.py
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

# Service account auth — credentials come from JSON key file, not OAuth.
# All Slack users share access to the delegated user's Google data.
# The delegated_user is the Google Workspace account being accessed.

service_account_file = getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
delegated_user = getenv("GOOGLE_DELEGATED_USER")

agent = Agent(
    name="Team Workspace Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(
            service_account_path=service_account_file,
            delegated_user=delegated_user,
            include_tools=["get_latest_emails", "search_emails", "get_message"],
        ),
        GoogleCalendarTools(
            service_account_path=service_account_file,
            delegated_user=delegated_user,
        ),
        GoogleDriveTools(
            service_account_path=service_account_file,
            delegated_user=delegated_user,
            include_tools=["list_files", "search_files", "read_file"],
        ),
    ],
    instructions=(
        "You are a team assistant with access to a shared Google Workspace. "
        "You can read the team inbox, check the team calendar, and search shared Drive files. "
        "All team members see the same data — this is a shared workspace, not personal accounts."
    ),
    markdown=True,
    add_datetime_to_context=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[Slack(agent=agent, reply_to_mentions_only=True)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    if not service_account_file:
        print("Missing env vars. Set:")
        print("  GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service_account.json")
        print("  GOOGLE_DELEGATED_USER=shared-inbox@yourcompany.com")
        print("  SLACK_TOKEN, SLACK_SIGNING_SECRET")
    else:
        agent_os.serve(app="workspace_service_account:app", reload=False)
