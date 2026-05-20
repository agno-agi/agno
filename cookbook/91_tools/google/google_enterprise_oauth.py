"""
Enterprise Google OAuth Configuration
======================================

Demonstrates hosted_domain restriction: only users from a specific Google
Workspace domain (e.g., @company.com) can authenticate.

Setup:
  1. Google Cloud Console -> OAuth consent screen -> Add your domain
  2. Create OAuth 2.0 Client ID (Desktop app for local testing)
  3. Export GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_enterprise_oauth.py
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.oauth_tools import GoogleOAuthTools

# Restrict OAuth to users from this domain only (set to None to allow all domains)
auth_config = GoogleAuthConfig(hosted_domain="agno.com")

agent = Agent(
    name="Enterprise OAuth Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=SqliteDb(db_file="tmp/enterprise_oauth.db", encrypt_auth_tokens=False),
    tools=[
        # store_token_in_db here auto-applies to all Google toolkits
        GoogleOAuthTools(auth_config=auth_config, store_token_in_db=True),
        GmailTools(include_tools=["get_latest_emails", "search_emails"]),
        GoogleCalendarTools(include_tools=["list_events", "create_event"]),
    ],
    instructions=(
        "You are an enterprise assistant with Gmail and Calendar access. "
        "If any Google tool returns an authentication error, call oauth_google."
    ),
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response("What tools do you have access to?")
