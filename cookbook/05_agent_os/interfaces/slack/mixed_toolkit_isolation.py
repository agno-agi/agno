"""
Mixed Toolkit Isolation Test
============================

Tests _clone_for_run() with a mix of toolkit types in multi-user Slack deployment:

1. Google toolkits (Gmail, Calendar) - isolation via contextvars, cloning is no-op
2. DuckDuckGoTools - stateless, cloning is harmless no-op
3. YFinanceTools - stateless, cloning is harmless no-op

This validates that mixed toolkit scenarios work correctly when user_id is set,
even though different toolkits use different isolation mechanisms.

The key insight:
- Google toolkits: @google_authenticate sets contextvars per-call
- Other toolkits: _clone_for_run() creates shallow copy per-run
- Both mechanisms can coexist in the same agent

Setup:
  1. Google Cloud Console -> Enable Gmail and Calendar APIs
  2. OAuth Client -> Authorized redirect URIs:
       https://<your-domain>/google/oauth/callback
  3. Slack App -> Event Subscriptions:
       https://<your-domain>/slack/events
  4. Env vars:
       SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
       GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
       GOOGLE_REDIRECT_URI=https://<your-domain>/google/oauth/callback
       GOOGLE_OAUTH_STATE_SECRET=<random-secret>

Run:
  .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/mixed_toolkit_isolation.py

Test scenarios:
  - User A asks: "What's AAPL stock price and search my emails for Apple"
  - User B asks: "Search news about Tesla and check my calendar"
  - Verify: User A's Gmail doesn't leak to User B, stock data is fresh per-call
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.oauth_tools import GoogleOAuthTools
from agno.tools.yfinance import YFinanceTools

db = SqliteDb(db_file="tmp/mixed_toolkit_test.db")

agent = Agent(
    name="Mixed Toolkit Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        # Google toolkits - isolation via contextvars
        GoogleOAuthTools(),
        GmailTools(include_tools=["get_latest_emails", "search_emails"]),
        GoogleCalendarTools(include_tools=["get_upcoming_events", "search_events"]),
        # Stateless toolkits - no isolation needed, cloning is harmless
        DuckDuckGoTools(),
        YFinanceTools(),
    ],
    instructions="""\
You are a multi-purpose assistant with access to:
- Gmail and Calendar (requires Google authentication)
- Web search via DuckDuckGo
- Stock information via YFinance

If any Google tool returns an authentication error, call oauth_google
and format the URL as: <URL|Click here to connect Google>

You can combine data from multiple sources to answer questions.
For example: search emails AND check stock prices in a single response.
""",
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
    agent_os.serve(app="mixed_toolkit_isolation:app", reload=False)
