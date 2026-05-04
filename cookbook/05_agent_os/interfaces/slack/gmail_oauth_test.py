"""
Google OAuth isolation test for multi-tenant Slack bot.

Tests Gmail, Calendar, and Drive tools with contextvar isolation.
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools

db = SqliteDb(db_file="/tmp/google_oauth_test.db")

redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
if not redirect_uri:
    ngrok_url = "https://paraphrastic-sang-ingenuous.ngrok-free.dev"
    redirect_uri = f"{ngrok_url}/google/oauth/callback"
    os.environ["GOOGLE_REDIRECT_URI"] = redirect_uri

if not os.getenv("GOOGLE_OAUTH_STATE_SECRET"):
    os.environ["GOOGLE_OAUTH_STATE_SECRET"] = "test-secret-for-oauth-state-signing"

google_auth = GoogleAuth()

gmail_tools = GmailTools(google_auth=google_auth, store_token_in_db=True)
calendar_tools = GoogleCalendarTools(google_auth=google_auth, store_token_in_db=True)
drive_tools = GoogleDriveTools(google_auth=google_auth, store_token_in_db=True)

agent = Agent(
    name="Google Test Bot",
    model=OpenAIResponses(id="gpt-4o"),
    tools=[google_auth, gmail_tools, calendar_tools, drive_tools],
    db=db,
    instructions=[
        "You help users with Gmail, Calendar, and Drive.",
        "For emails: show sender, subject, snippet.",
        "For calendar: show event title, time, attendees.",
        "For drive: show file name, type, modified date.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[
        Slack(
            agent=agent,
            token=os.getenv("SLACK_TOKEN"),
            signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
            reply_to_mentions_only=True,
        )
    ],
)
app = agent_os.get_app()
app.include_router(google_auth.get_oauth_router(db=db))

if __name__ == "__main__":
    print("Starting Google OAuth test bot (Gmail + Calendar + Drive) on port 7777")
    print(f"Redirect URI: {redirect_uri}")
    agent_os.serve(app="gmail_oauth_test:app", host="0.0.0.0", port=7777)
