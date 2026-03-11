"""
Gmail OAuth Slack Bot
=====================

Slack bot with per-user Google OAuth for Gmail access.

Each Slack user authenticates independently with Google. Tokens are
stored encrypted in a local SQLite database.

Setup:
  1. Set environment variables:
       SLACK_TOKEN, SLACK_SIGNING_SECRET,
       GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
       GOOGLE_OAUTH_ENCRYPTION_KEY  (run: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
       SSL_CERT_FILE               (macOS: python -c "import certifi; print(certifi.where())")

  2. Add your tunnel URL as an authorized redirect URI in Google Cloud Console:
       https://console.cloud.google.com/auth/clients
       Redirect URI: <TUNNEL_URL>/google/auth/callback

  3. Start a tunnel:
       cloudflared tunnel --url http://localhost:7777

  4. Run the bot:
       GOOGLE_OAUTH_BASE_URL=<TUNNEL_URL> .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/gmail_oauth.py

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, im:write
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.google.gmail import GmailTools
from agno.tools.google.oauth.router import create_google_oauth_router
from agno.tools.google.oauth.token_store import SqliteGoogleTokenStore

GOOGLE_OAUTH_BASE_URL = getenv("GOOGLE_OAUTH_BASE_URL", "http://localhost:7777")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Shared token store — per-user credentials encrypted at rest
token_store = SqliteGoogleTokenStore(
    db_path="tmp/google_oauth_tokens.db",
    encryption_key=getenv("GOOGLE_OAUTH_ENCRYPTION_KEY"),
)

gmail_tools = GmailTools(
    token_store=token_store,
    get_latest_emails=True,
    search_emails=True,
    send_email=True,
    create_draft_email=True,
)

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/gmail_oauth.db")

gmail_agent = Agent(
    name="Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[gmail_tools],
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    instructions=[
        "You are a helpful assistant with access to the user's Gmail.",
        "You can read, search, and send emails on their behalf.",
        "If the user hasn't connected their Google account yet, let them know.",
    ],
)

# Google OAuth router handles /google/auth/initiate and /google/auth/callback
google_oauth_router = create_google_oauth_router(
    token_store=token_store,
    redirect_uri=f"{GOOGLE_OAUTH_BASE_URL}/google/auth/callback",
    scopes=GMAIL_SCOPES,
    slack_token=getenv("SLACK_TOKEN"),
)

agent_os = AgentOS(
    agents=[gmail_agent],
    interfaces=[
        Slack(
            agent=gmail_agent,
            reply_to_mentions_only=False,
            google_oauth_base_url=GOOGLE_OAUTH_BASE_URL,
        )
    ],
)

app = agent_os.get_app()
# Mount OAuth routes alongside the Slack interface
app.include_router(google_oauth_router)

if __name__ == "__main__":
    agent_os.serve(app="gmail_oauth:app", reload=True)
