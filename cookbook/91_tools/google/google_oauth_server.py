"""
Multi-User Gmail Agent with AgentOS
===================================

Production-ready pattern: AgentOS server with OAuth callback endpoint.
Users authenticate via Google OAuth, tokens stored in DB per user_id.

Architecture:
  1. User visits your app and triggers OAuth flow
  2. Google redirects to /google/oauth/callback with auth code
  3. Callback exchanges code for tokens, stores in DB keyed by user_id
  4. Subsequent requests use stored token — no re-auth needed

Authentication (env vars):
  GOOGLE_CLIENT_ID         - OAuth client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET     - OAuth client secret
  GOOGLE_OAUTH_STATE_SECRET - HMAC key for signing state JWT (security)

Setup:
  1. Enable Gmail API at console.cloud.google.com
  2. Create OAuth credentials (Web application, not Desktop)
  3. Add redirect URI: http://localhost:8000/google/oauth/callback
  4. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_OAUTH_STATE_SECRET

Run:
  GOOGLE_OAUTH_STATE_SECRET=your-secret python google_oauth_server.py
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.google.auth import GoogleAuth, OAuthConfig
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Database for Token Storage
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/google_oauth_server.db")

# ---------------------------------------------------------------------------
# Shared Auth Config
# ---------------------------------------------------------------------------

auth = GoogleAuth(
    client_id=getenv("GOOGLE_CLIENT_ID"),
    client_secret=getenv("GOOGLE_CLIENT_SECRET"),
    oauth_config=OAuthConfig(
        db=db,
        state_secret=getenv("GOOGLE_OAUTH_STATE_SECRET"),
        store_tokens=True,
        enable_multi_user_oauth=True,
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

gmail_agent = Agent(
    name="Gmail Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GmailTools(auth=auth, include_tools=["get_latest_emails", "search_emails"]),
    ],
    instructions="You are a Gmail assistant. Help users manage their email.",
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    name="Google OAuth Demo",
    agents=[gmail_agent],
    db=db,
)
app = agent_os.get_app()

# Mount OAuth callback router
app.include_router(auth.create_router())

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run: GOOGLE_OAUTH_STATE_SECRET=secret python google_oauth_server.py

    Setup:
      1. Enable Gmail API at console.cloud.google.com
      2. Create OAuth credentials (Web application)
      3. Add redirect URI: http://localhost:8000/google/oauth/callback
      4. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_OAUTH_STATE_SECRET
    """
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
