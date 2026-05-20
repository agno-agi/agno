"""
Enterprise Google OAuth Configuration
======================================

Demonstrates hosted_domain restriction: only users from a specific Google
Workspace domain (e.g., @company.com) can authenticate.

Setup:
  1. Google Cloud Console -> OAuth consent screen -> Add your domain
  2. Create OAuth 2.0 Client ID (Desktop app for local testing)
  3. Export env vars:
       GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
       GOOGLE_HOSTED_DOMAIN=company.com  # Restrict to this domain

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_enterprise_oauth.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleOAuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.oauth_tools import GoogleOAuthTools

hosted_domain = os.getenv("GOOGLE_HOSTED_DOMAIN")
oauth_config = GoogleOAuthConfig(hosted_domain=hosted_domain)

agent = Agent(
    name="Enterprise OAuth Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=SqliteDb(db_file="tmp/enterprise_oauth.db", encrypt_auth_tokens=False),
    tools=[
        GoogleOAuthTools(oauth_config=oauth_config),
        GmailTools(include_tools=["get_latest_emails", "search_emails"], store_token_in_db=True),
        GoogleCalendarTools(include_tools=["list_events", "create_event"], store_token_in_db=True),
    ],
    instructions=(
        "You are an enterprise assistant with Gmail and Calendar access. "
        "If any Google tool returns an authentication error, call oauth_google."
    ),
    markdown=True,
)


if __name__ == "__main__":
    print(f"Hosted domain restriction: {hosted_domain or 'none (all domains allowed)'}")
    agent.print_response("What tools do you have access to?")
