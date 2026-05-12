"""
Enterprise Google OAuth Configuration
======================================

Demonstrates enterprise-grade OAuth features:
- hosted_domain: Restrict to specific Google Workspace domain (@company.com)
- login_hint: Pre-fill email in Google's login form
- Token encryption at rest (configured on DB)

Setup:
  1. Google Cloud Console -> OAuth consent screen -> Add your domain
  2. Create OAuth 2.0 Client ID (Web application for server, Desktop for local)
  3. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_HOSTED_DOMAIN env vars

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

oauth_config = GoogleOAuthConfig(
    hosted_domain=os.getenv("GOOGLE_HOSTED_DOMAIN"),
    login_hint=os.getenv("GOOGLE_LOGIN_HINT"),
)

# Encryption configured once on DB — all toolkits inherit it
db = SqliteDb(
    db_file="tmp/enterprise_oauth.db",
    encrypt_auth_tokens=True,
    auth_token_encryption_key=os.getenv("AGNO_ENCRYPTION_KEY"),
)

agent = Agent(
    name="Enterprise OAuth Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GoogleOAuthTools(oauth_config=oauth_config),
        GmailTools(
            oauth_config=oauth_config,
            include_tools=["get_latest_emails", "search_emails"],
        ),
        GoogleCalendarTools(
            oauth_config=oauth_config, include_tools=["list_events", "create_event"]
        ),
    ],
    instructions=(
        "You are an enterprise assistant with Gmail and Calendar access. "
        "If any Google tool returns an authentication error, call oauth_google."
    ),
    markdown=True,
)


if __name__ == "__main__":
    print(f"Hosted domain: {oauth_config._hosted_domain or 'all domains'}")
    print(f"Token encryption: {'enabled' if db.encrypt_auth_tokens else 'disabled'}")
    agent.print_response("What tools do you have access to?")
