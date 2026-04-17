"""
Google Workspace Agent with Shared DB Token Storage
====================================================
Single agent with Gmail + Calendar + Drive, all sharing ONE OAuth token via
the GoogleAuth coordinator. Token persists to SqliteDb — the user consents
once and the token is reused across all three toolkits on subsequent runs.

Pattern:
    one GoogleAuth instance
    + N Google toolkits (gmail, calendar, drive)
    = one OAuth URL covering the union of all requested scopes
      one DB row under service="google", reused everywhere.

Setup:
1. Enable Gmail, Calendar, and Drive APIs at https://console.cloud.google.com
2. Create OAuth 2.0 credentials (Desktop app).
3. Export the credentials:
       export GOOGLE_CLIENT_ID=your_client_id
       export GOOGLE_CLIENT_SECRET=your_client_secret
4. pip install openai google-api-python-client google-auth-httplib2 \\
               google-auth-oauthlib
5. First run (cookbook / local): a browser window opens to Google's consent
   screen with ALL three toolkits' scopes bundled into one consent flow.
   After you click through, the token is saved to tmp/google_workspace_db.db
   and reused on subsequent runs.
6. For Slack/AgentOS deployments, mount the OAuth callback router instead:
       app.include_router(google_auth.get_oauth_router())
   The act of mounting the router switches GoogleAuth into interface mode,
   where the agent returns an OAuth URL (via the authenticate_google tool)
   instead of opening a local browser. See cookbook/05_agent_os/ for hosted
   examples.
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

# Multi-toolkit scope carry-over: Google skips re-consent for tools the user already
# approved under this OAuth client. Per-scope revocation moves to account settings.
google_auth = GoogleAuth(include_granted_scopes=True)

gmail = GmailTools(
    google_auth=google_auth,
    include_tools=["get_latest_emails", "search_emails"],
)

calendar = GoogleCalendarTools(
    google_auth=google_auth,
    create_event=False,
    update_event=False,
    delete_event=False,
)

drive = GoogleDriveTools(
    google_auth=google_auth,
    include_tools=["list_files", "search_files"],
)

agent = Agent(
    name="Workspace Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[google_auth, gmail, calendar, drive],
    db=SqliteDb(db_file="tmp/google_workspace_db.db"),
    instructions=[
        "You are a Google Workspace assistant with access to Gmail, Calendar, and Drive.",
        "When any Google tool returns an authentication error, immediately call",
        "authenticate_google with the services you need and share the OAuth URL",
        "with the user so they can complete the consent flow.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "What are my 3 most recent emails, and do I have any meetings today?",
        stream=True,
    )
