"""
DB-Backed Google OAuth Token Storage
=====================================
Store Google OAuth tokens in a database for multi-user persistence.
Tokens survive server restarts and are scoped per user_id.

Flow:
1. Agent has GoogleAuth + GmailTools + SqliteDb
2. agent.db auto-wires to google_auth._db at tool resolution time
3. No token in DB -> agent returns OAuth URL for the user to visit
4. After OAuth callback stores token, subsequent calls load from DB
5. Expired tokens auto-refresh via refresh_token (no re-auth)

This cookbook demonstrates the DB auth flow. On first run the agent will
return an OAuth URL since no token exists yet. For end-to-end OAuth with
a callback server, see the Slack/WhatsApp interface cookbooks.

Setup:
1. Export GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars
2. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# GoogleAuth coordinates scopes and manages token persistence.
# The agent's db= is auto-wired to google_auth._db at tool resolution time,
# so GoogleAuth does NOT need a db= param here.
google_auth = GoogleAuth()

agent = Agent(
    name="Gmail Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        google_auth,
        GmailTools(
            google_auth=google_auth,
            include_tools=["get_latest_emails", "search_emails"],
        ),
    ],
    db=SqliteDb(db_file="tmp/google_auth.db"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # First run: no token in DB, agent calls authenticate_google and returns
    # an OAuth URL. In an interface (Slack, WhatsApp), the user clicks it.
    agent.print_response(
        "List my 3 most recent emails",
        stream=True,
        user_id="user-1",
    )

    # After OAuth completes and token is stored in DB, subsequent runs
    # load the token from DB automatically. No browser, no token.json.
    # agent.print_response(
    #     "Search my emails for messages about 'project update'",
    #     stream=True,
    #     user_id="user-1",
    # )
