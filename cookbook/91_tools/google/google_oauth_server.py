"""
Google OAuth Server with AgentOS
================================

Run a multi-user Gmail agent as a web server. Users authenticate via OAuth
callback, and tokens are stored in the database for reuse.

Key features:
- AgentOS auto-mounts /google/oauth/callback from GoogleOAuthTools
- Tokens persisted in SqliteDb (or PostgresDb for production)
- Multi-user: each user_id gets their own token
- Works with Slack, WhatsApp, or any interface that passes user_id

Setup:
  1. Enable Gmail API at https://console.cloud.google.com
  2. Create OAuth 2.0 credentials (Web application, not Desktop)
  3. Add authorized redirect URI: http://localhost:8000/google/oauth/callback
  4. Export env vars:
       export GOOGLE_CLIENT_ID=...
       export GOOGLE_CLIENT_SECRET=...
       export GOOGLE_REDIRECT_URI=http://localhost:8000/google/oauth/callback
  5. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/google_oauth_server.py

Test:
  1. Open http://localhost:8000/google/oauth/callback?initiate=true in browser
  2. Complete Google OAuth consent
  3. Call the agent API with user_id to use the stored token

For production:
  - Use PostgresDb instead of SqliteDb
  - Set GOOGLE_REDIRECT_URI to your public URL (e.g., https://your-app.com/google/oauth/callback)
  - Use ngrok or cloudflared for local development with public URL
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.google.gmail import GmailTools
from agno.tools.google.oauth_tools import GoogleOAuthTools

db = SqliteDb(
    db_file="tmp/google_oauth_server.db",
    store_auth_tokens=True,
    encrypt_auth_tokens=False,
)

gmail_agent = Agent(
    name="Gmail Agent",
    agent_id="gmail-agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GoogleOAuthTools(),
        GmailTools(include_tools=["get_latest_emails", "search_emails"]),
    ],
    instructions="You are a Gmail assistant. Help users manage their email.",
    add_datetime_to_context=True,
    markdown=True,
)

app = AgentOS(
    name="Google OAuth Demo",
    agents=[gmail_agent],
    db=db,
)

if __name__ == "__main__":
    app.serve(port=8000)
