"""
Gmail Agent with DB Token Storage
==================================
Gmail agent that saves OAuth tokens to a database instead of token.json.
First run opens a browser for consent, token persists in DB for next time.

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Gmail API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Gmail Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(
            store_token_in_db=True,
            include_tools=["get_latest_emails", "search_emails"],
        ),
    ],
    db=SqliteDb(db_file="tmp/gmail_tokens.db"),
    instructions=[
        "You are a Gmail assistant. Summarize emails clearly.",
        "Show sender, subject, and a brief preview for each email.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Show me my 3 most recent emails",
        stream=True,
    )
