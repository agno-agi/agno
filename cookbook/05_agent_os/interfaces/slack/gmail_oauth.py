"""
Slack + Gmail & Calendar OAuth
==============================

Slack bot with per-user Gmail and Calendar access. First time a user asks,
the agent returns an OAuth URL. After consent, token persists in DB.

Setup:
  1. Google Cloud Console -> Enable Gmail and Calendar APIs
  2. OAuth Client -> Authorized redirect URIs:
       https://<your-domain>/google/oauth/callback
  3. Slack App -> Event Subscriptions:
       https://<your-domain>/slack/events
  4. Env vars:
       SLACK_TOKEN, SLACK_SIGNING_SECRET
       GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
       GOOGLE_REDIRECT_URI=https://<your-domain>/google/oauth/callback
       GOOGLE_OAUTH_STATE_SECRET=<random-secret>  # CSRF protection

     Generate secrets with: python -c "import secrets; print(secrets.token_urlsafe(32))"

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/gmail_oauth.py
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.google import GoogleAuth, OAuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools

db = SqliteDb(db_file="tmp/slack_gmail_calendar.db")

# Shared auth config — single OAuth consent covers Gmail + Calendar
# enable_multi_user_oauth=True: on auth failure, returns OAuth URL instead of browser fallback
config = GoogleAuth(
    client_id=getenv("GOOGLE_CLIENT_ID"),
    client_secret=getenv("GOOGLE_CLIENT_SECRET"),
    redirect_uri=getenv("GOOGLE_REDIRECT_URI"),
    oauth_config=OAuthConfig(
        db=db,
        state_secret=getenv("GOOGLE_OAUTH_STATE_SECRET"),
        store_tokens=True,
        enable_multi_user_oauth=True,
    ),
)

agent = Agent(
    name="Gmail & Calendar Slack Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GmailTools(auth=config, include_tools=["get_latest_emails", "search_emails"]),
        GoogleCalendarTools(auth=config),
    ],
    instructions=(
        "You are a Google assistant in Slack with Gmail and Calendar access. "
        "When authentication fails, share the OAuth URL with the user as a clickable link."
    ),
    markdown=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[Slack(agent=agent, reply_to_mentions_only=True)],
)
app = agent_os.get_app()

# Mount OAuth callback router
app.include_router(config.create_router())


if __name__ == "__main__":
    agent_os.serve(app="gmail_oauth:app", reload=False)
