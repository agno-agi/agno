"""Multi-user Gmail agent with AgentOS and OAuth callback."""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.google.gmail import GmailTools
from agno.tools.google.oauth_tools import GoogleOAuthTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db = SqliteDb(
    db_file="tmp/google_oauth_server.db",
    store_auth_tokens=True,
    encrypt_auth_tokens=False,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

gmail_agent = Agent(
    name="Gmail Agent",
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

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    name="Google OAuth Demo",
    agents=[gmail_agent],
    db=db,
)
app = agent_os.get_app()

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

    AgentOS auto-mounts /google/oauth/callback from GoogleOAuthTools.
    """
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
