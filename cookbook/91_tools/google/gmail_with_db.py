"""
Gmail Agent with DB Token Storage
==================================
Gmail agent that persists OAuth tokens in a database. First run opens a
browser for consent as usual, but the token is saved to the DB alongside
token.json. On subsequent runs, creds load from DB first.

No GoogleAuth needed — just set store_token_in_db=True on the toolkit
and pass db= to the agent. Auto-wiring handles the rest.

Key concepts:
- store_token_in_db=True: opt-in to DB token persistence
- agent.db auto-wires to toolkit._db at tool resolution time
- File-based OAuth flow opens browser as usual for initial consent
- Token is saved to DB only (not token.json) when store_token_in_db=True
- On next run, token loads from DB — no file, no browser

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Gmail API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
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
