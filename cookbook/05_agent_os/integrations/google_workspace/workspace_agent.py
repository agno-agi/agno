"""
Google Workspace Agent via MCP
==============================

A personal assistant that can manage your Gmail, Google Drive, and Google Calendar
using the Google Workspace CLI (gws) as an MCP server.

Prerequisites:
    1. Install gws CLI:
        npm install -g @googleworkspace/cli

    2. Authenticate:
        gws auth setup

    3. Set environment variables:
        export OPENAI_API_KEY=your-openai-api-key

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_agent.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/workspace_agent.db")

# Connect to Google Workspace via gws MCP server
# gws dynamically discovers all available API methods and exposes them as tools.
# Use -s to select which services to expose (keeps tool count manageable).
workspace_tools = MCPTools(
    command="gws",
    args=["mcp", "-s", "gmail,drive,calendar"],
)

workspace_agent = Agent(
    id="workspace-agent",
    name="Workspace Assistant",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[workspace_tools],
    instructions=[
        "You are a personal workspace assistant with access to Gmail, Google Drive, and Google Calendar.",
        "When the user asks about emails, use Gmail tools to search and read messages.",
        "When the user asks about files or documents, use Drive tools to find and manage them.",
        "When the user asks about meetings or scheduling, use Calendar tools.",
        "Always summarize results clearly and highlight actionable items.",
        "If a request spans multiple services (e.g., 'find the document John emailed me'), "
        "combine tools from different services to fulfill it.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    description="Google Workspace assistant powered by gws MCP",
    agents=[workspace_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="workspace_agent:app", reload=True)
