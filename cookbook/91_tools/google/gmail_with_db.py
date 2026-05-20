"""
Gmail Agent with DB Token Storage
==================================

Gmail agent that saves OAuth tokens to database instead of token.json.
First run opens browser for consent, token persists in DB for reuse.

Setup:
  1. Enable Gmail API at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Desktop app)
  3. Export GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars
  4. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Note: Token encryption is disabled for simpler local dev. For production,
remove `encrypt_auth_tokens=False` and set AGNO_ENCRYPTION_KEY.

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/gmail_with_db.py
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.gmail import GmailTools

agent = Agent(
    name="Gmail Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    # encrypt_auth_tokens=False for simpler local dev (no AGNO_ENCRYPTION_KEY needed)
    db=SqliteDb(db_file="tmp/gmail_tokens.db", encrypt_auth_tokens=False),
    tools=[GmailTools(include_tools=["get_latest_emails", "search_emails"], store_token_in_db=True)],
    instructions="You are a Gmail assistant. Show sender, subject, and brief preview for each email.",
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Show me my 3 most recent emails", stream=True, user_id="user-1"
    )
