"""
Google Workspace Agent (Gmail + Calendar + Drive)
=================================================
A single agent with access to Gmail, Calendar, and Drive. First run opens
a browser for OAuth consent — one token.json covers all APIs.

Key concepts:
- Multiple Google toolkits on one agent share a single token.json
- add_datetime_to_context: agent knows "now" for time-aware queries

Setup:
1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
2. Create OAuth 2.0 credentials (Desktop app) and download credentials.json
   OR export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Workspace Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GmailTools(
            include_tools=["get_latest_emails", "search_emails", "create_draft_email"],
        ),
        GoogleCalendarTools(
            create_event=False,
            update_event=False,
            delete_event=False,
        ),
        GoogleDriveTools(
            include_tools=["list_files", "search_files", "read_file"],
        ),
    ],
    instructions=[
        "You are a Google Workspace assistant with access to Gmail, Calendar, and Drive.",
        "When asked about recent activity, check emails and calendar events.",
        "When asked about documents, search Drive.",
        "Summarize findings in a clear, structured format.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "What are my 3 most recent emails and do I have any meetings today?",
        stream=True,
    )

    # Cross-service query
    # agent.print_response(
    #     "Find recent emails about 'quarterly report' and check if there are "
    #     "related files in my Drive",
    #     stream=True,
    # )
