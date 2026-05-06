"""
Slack + Google OAuth (hosted mode)
==================================

Slack bot that reads Gmail per-user. First time a user asks, the agent returns
an OAuth URL signed with a JWT state (stored nowhere per-flow). Clicking the URL
completes consent → /google/oauth/callback → token persists → subsequent runs hit
the hot path.

Setup:
  1. Google Cloud Console → OAuth Client → Authorized redirect URIs:
       https://<your-ngrok>.ngrok-free.dev/google/oauth/callback
  2. Slack App → Event Subscriptions → Request URL:
       https://<your-ngrok>.ngrok-free.dev/slack/events
  3. Env: SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, GOOGLE_CLIENT_ID,
          GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI (set to the full callback URL)

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/gmail_oauth.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.gmail import GmailTools

db = SqliteDb(db_file="tmp/slack_gmail_oauth.db")

google_auth = GoogleAuth(
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    redirect_uri=os.environ["GOOGLE_REDIRECT_URI"],
)

agent = Agent(
    name="Gmail Slack Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        google_auth,
        GmailTools(
            auth=google_auth,
            include_tools=["get_latest_emails", "search_emails"],
        ),
    ],
    instructions=(
        "You are a Gmail assistant in Slack. If any Gmail tool returns an authentication error, "
        "IMMEDIATELY call `oauth_google` with services=['gmail'] and send the resulting URL "
        "to the user. Tell them to click it, complete consent, then retry their request."
    ),
    markdown=True,
    add_history_to_context=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[Slack(agent=agent, reply_to_mentions_only=True)],
)
app = agent_os.get_app()

# Mount the OAuth callback router on the same FastAPI app
app.include_router(google_auth.get_oauth_router())


if __name__ == "__main__":
    agent_os.serve(app="gmail_oauth:app", host="0.0.0.0", port=7778, reload=False)
