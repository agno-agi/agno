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
        export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_agent.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/workspace_agent.db")

# Pass relevant env vars so the gws subprocess can find credentials
gws_env = {
    k: v
    for k, v in os.environ.items()
    if k.startswith("GOOGLE_WORKSPACE_CLI_") or k in ("HOME", "PATH", "USER")
}

# Use include_tools to keep the tool count under OpenAI's 128 limit.
# gmail + drive + calendar exposes ~173 tools total; pick the most useful ones.
workspace_tools = MCPTools(
    command="gws mcp -s gmail,drive,calendar",
    env=gws_env,
    include_tools=[
        # Gmail
        "gmail_users_messages_list",
        "gmail_users_messages_get",
        "gmail_users_messages_send",
        "gmail_users_labels_list",
        # Drive
        "drive_files_list",
        "drive_files_get",
        "drive_files_create",
        # Calendar
        "calendar_events_list",
        "calendar_events_get",
        "calendar_events_insert",
    ],
)

workspace_agent = Agent(
    id="workspace-agent",
    name="Workspace Assistant",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[workspace_tools],
    instructions=[
        "You are a personal workspace assistant with access to Gmail, Google Drive, and Google Calendar.",
        "All gws tools accept a 'params' object for path/query parameters.",
        "Every parameter (path and query) must go inside the params dict.",
        "To list messages: gmail_users_messages_list(params={'userId': 'me', 'maxResults': 5})",
        "To get a message: gmail_users_messages_get(params={'userId': 'me', 'id': '<messageId>', 'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']})",
        "Always use format='metadata' when reading messages to keep responses small.",
        "For Calendar, always pass params={'calendarId': 'primary'}.",
        "For Drive, no special path params needed for listing files.",
        "Always summarize results clearly and highlight actionable items.",
        "If a request spans multiple services, combine tools to fulfill it.",
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
