"""
Enterprise Google OAuth Configuration
======================================

Demonstrates enterprise-grade Google OAuth features:
- hosted_domain (hd): Restrict authentication to specific Google Workspace domain
- access_type: Control offline vs online access
- prompt: Control consent screen behavior
- login_hint: Pre-fill email address
- Automatic scope consolidation across multiple Google toolkits

Two modes:
1. Bot/Service Account (default): Use pre-configured credentials, no OAuth needed
2. Client-Side OAuth (opt-in): Pass `google_auth=` on the Agent to enable per-user authentication

Setup:
  1. Google Cloud Console -> OAuth consent screen -> Add your domain
  2. Create OAuth 2.0 Client ID (Web application type for hosted, Desktop for local)
  3. Set env vars: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_HOSTED_DOMAIN

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_enterprise_oauth.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools

# Mode 1: Bot/Service Account (default credentials, no OAuth)
# Use when you have pre-configured credentials (like Coda's bot token)
bot_agent = Agent(
    name="Bot Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GmailTools(include_tools=["get_latest_emails"]),
        GoogleCalendarTools(include_tools=["list_events"]),
    ],
    instructions="You have Gmail and Calendar access via service account.",
    markdown=True,
)


# Mode 2: Client-Side OAuth (opt-in for per-user auth)
# Use when users need to authenticate their own Google accounts
google_auth = GoogleAuth(
    # Restrict to specific Google Workspace domain (e.g., @acme.com)
    hosted_domain=os.getenv("GOOGLE_HOSTED_DOMAIN"),
    # Control consent behavior: "consent", "select_account", or "none"
    prompt="consent",
    # Control refresh token: "offline" (get refresh token) or "online"
    access_type="offline",
    # Pre-fill email in Google's login form
    login_hint=os.getenv("GOOGLE_LOGIN_HINT"),
    # Carry forward previously granted scopes
    include_granted_scopes=True,
    # Encrypt tokens at rest in DB
    encrypt_tokens=True,
)

oauth_agent = Agent(
    name="Enterprise OAuth Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=SqliteDb(db_file="tmp/enterprise_oauth.db"),
    # First-class agent param — framework injects the coordinator into every
    # GoogleToolkit and auto-registers `oauth_google` as a model-callable tool.
    google_auth=google_auth,
    tools=[
        GmailTools(include_tools=["get_latest_emails", "search_emails"]),
        GoogleCalendarTools(include_tools=["list_events", "create_event"]),
    ],
    instructions=(
        "You are an enterprise assistant with access to Gmail and Calendar. "
        "If any Google tool returns an authentication error, call oauth_google "
        "and provide the OAuth URL to the user."
    ),
    markdown=True,
)


if __name__ == "__main__":
    print("Enterprise Google OAuth Configuration Demo")
    print("=" * 50)

    print("\n--- Mode 1: Bot/Service Account ---")
    print("Using pre-configured credentials, no OAuth flow needed.")
    bot_agent.print_response("What tools do you have access to?")

    print("\n--- Mode 2: Client-Side OAuth ---")
    print(f"Hosted domain: {google_auth._hosted_domain or 'None (all domains)'}")
    print(f"Access type: {google_auth._access_type}")
    print(f"Prompt mode: {google_auth._prompt}")
    print(f"Token encryption: {google_auth._encrypt_tokens}")
    print("\noauth_google auto-registered via agent.google_auth.")
    oauth_agent.print_response("What tools do you have access to?")
