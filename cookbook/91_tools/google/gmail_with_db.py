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
    db=SqliteDb(db_file="tmp/gmail_tokens.db"),
    tools=[
        GmailTools(
            store_token_in_db=True,
            include_tools=["get_latest_emails", "search_emails"],
        )
    ],
    instructions="You are a Gmail assistant. Show sender, subject, and brief preview for each email.",
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Show me my 3 most recent emails", stream=True, user_id="user-1"
    )
