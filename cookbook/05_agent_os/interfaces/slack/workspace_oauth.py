"""
Slack + Google Workspace OAuth (Gmail + Calendar + Drive)
==========================================================

Full Google Workspace assistant in Slack with per-user OAuth. Single consent
flow covers Gmail + Calendar + Drive scopes.

Setup:
  1. Google Cloud Console -> Enable Gmail, Calendar, and Drive APIs
  2. OAuth Client -> Authorized redirect URIs:
       https://<your-domain>/google/oauth/callback
     (AgentOS auto-mounts this route when GoogleOAuthTools is present)
  3. Slack App -> Event Subscriptions:
       https://<your-domain>/slack/events
  4. Env vars:
       SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
       GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
       GOOGLE_REDIRECT_URI=https://<your-domain>/google/oauth/callback

     To customize the callback path:
       GoogleOAuthConfig(callback_path="/auth/google/callback")
       Then set GOOGLE_REDIRECT_URI to match.

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/workspace_oauth.py
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.oauth_tools import GoogleOAuthTools

db = SqliteDb(db_file="tmp/slack_workspace_oauth.db")

agent = Agent(
    name="Workspace Slack Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        GoogleOAuthTools(),
        GmailTools(include_tools=["get_latest_emails", "search_emails", "get_message"]),
        GoogleCalendarTools(),
        GoogleDriveTools(include_tools=["list_files", "search_files", "read_file"]),
    ],
    instructions=(
        "You are a Google Workspace assistant in Slack with Gmail, Calendar, and Drive access. "
        "If any Google tool returns an authentication error, call oauth_google "
        "and format the URL as: <URL|Connect Google Workspace>"
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


if __name__ == "__main__":
    agent_os.serve(app="workspace_oauth:app", reload=False)
