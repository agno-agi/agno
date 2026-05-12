"""
Google Workspace Agent (Gmail + Calendar + Drive)
=================================================

Single agent with Gmail, Calendar, and Drive access. First run opens browser
for OAuth consent — one token.json covers all three APIs.

Setup:
  1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET env vars
     OR download credentials.json to working directory
  4. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_workspace_agent.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(
            include_tools=["get_latest_emails", "search_emails", "create_draft_email"]
        ),
        GoogleCalendarTools(create_event=False, update_event=False, delete_event=False),
        GoogleDriveTools(include_tools=["list_files", "search_files", "read_file"]),
    ],
    instructions=(
        "You are a Google Workspace assistant with Gmail, Calendar, and Drive access. "
        "Summarize findings clearly and concisely."
    ),
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "What are my 3 most recent emails and do I have any meetings today?",
        stream=True,
    )
