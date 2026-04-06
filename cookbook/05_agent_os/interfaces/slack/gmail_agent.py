"""
Slack Gmail Agent (DB-backed OAuth)
====================================

Slack bot that can read/send Gmail using DB-backed OAuth tokens.
When a user asks about email, the agent checks the DB for stored tokens.
If none exist, it returns an OAuth URL the user clicks to authenticate.

Setup:
  1. Google Cloud: Create OAuth 2.0 Web Application credentials
     - Authorized redirect URI: https://<your-ngrok>/google/oauth/callback
  2. Set env vars:
     - GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
     - GOOGLE_REDIRECT_URI=https://<your-ngrok>/google/oauth/callback
     - SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
     - OPENAI_API_KEY
  3. Start pgvector: ./cookbook/scripts/run_pgvector.sh
  4. Start ngrok:    ngrok http 7777
  5. Run:            .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/gmail_agent.py

Flow:
  User: "What are my latest emails?"
  Bot:  Returns OAuth URL (first time) -> user clicks -> Google consent -> callback saves token
  User: Retries -> Bot reads Gmail via stored token
"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.gmail import GmailTools

# ---------------------------------------------------------------------------
# Database (shared between agent session storage and OAuth token storage)
# ---------------------------------------------------------------------------

db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Google Auth + Gmail
# ---------------------------------------------------------------------------

google_auth = GoogleAuth()

gmail = GmailTools(
    google_auth=google_auth,
    get_latest_emails=True,
    get_emails_from_user=True,
    get_unread_emails=True,
    search_emails=True,
    send_email=True,
    create_draft_email=True,
)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

gmail_agent = Agent(
    name="Gmail Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[google_auth, gmail],
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    instructions=[
        "You are a helpful email assistant connected to Gmail.",
        "When authentication is needed, share the OAuth URL and ask the user to click it.",
        "After they authenticate, retry the original request.",
    ],
)

# ---------------------------------------------------------------------------
# AgentOS + Slack + OAuth callback
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[gmail_agent],
    interfaces=[
        Slack(
            agent=gmail_agent,
            reply_to_mentions_only=True,
            resolve_user_identity=True,
        )
    ],
)

app = agent_os.get_app()

# Attach the OAuth callback endpoint to the same FastAPI app
# Google redirects here after user consents: /google/oauth/callback?code=...&state=...
app.include_router(google_auth.get_oauth_router())


if __name__ == "__main__":
    agent_os.serve(app="gmail_agent:app", reload=True)
