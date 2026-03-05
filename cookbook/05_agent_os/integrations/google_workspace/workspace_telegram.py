"""
Google Workspace Agent on Telegram
===================================

Deploy your Workspace assistant to Telegram so you can manage
emails, files, and calendar from your phone.

Prerequisites:
    1. Install gws CLI:
        npm install -g @googleworkspace/cli

    2. Authenticate gws:
        gws auth setup

    3. Set environment variables:
        export OPENAI_API_KEY=your-openai-api-key
        export TELEGRAM_TOKEN=your-telegram-bot-token

    4. Set up webhook (use ngrok for local development):
        ngrok http 7777
        curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook?url=https://YOUR_NGROK_URL/telegram/webhook"

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_telegram.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.telegram import Telegram
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/workspace_telegram.db")

workspace_tools = MCPTools(
    command="gws",
    args=["mcp", "-s", "gmail,drive,calendar"],
)

workspace_agent = Agent(
    id="workspace-tg-agent",
    name="Workspace Bot",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[workspace_tools],
    instructions=[
        "You are a Workspace assistant on Telegram.",
        "Keep responses concise and mobile-friendly.",
        "Use bullet points for lists of emails, files, or events.",
        "For emails, show: sender, subject, and a one-line summary.",
        "For events, show: title, time, and location.",
        "Always confirm before sending emails or creating events.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS with Telegram interface
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    description="Google Workspace assistant on Telegram",
    agents=[workspace_agent],
    interfaces=[
        Telegram(agent=workspace_agent),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="workspace_telegram:app", reload=True)
