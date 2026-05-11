"""
GoogleAuth with DB Token Storage
=================================
Multi-toolkit agent using GoogleAuth to consolidate OAuth scopes.
Tokens persist in DB. On first run, the agent returns an OAuth URL
since no token exists yet.

For end-to-end OAuth with a callback server, see the interface cookbooks.

Setup:
1. Export GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars
2. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Gmail Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=SqliteDb(db_file="tmp/google_auth.db"),
    google_auth=GoogleAuth(),
    tools=[GmailTools(include_tools=["get_latest_emails", "search_emails"])],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "List my 3 most recent emails",
        stream=True,
        user_id="user-1",
    )
