"""
Google Workspace Agent — Full Suite
====================================

Same as workspace_agent.py but with tools from all major Workspace services:
Gmail, Drive, Calendar, Sheets, Docs, and Chat.

Uses include_tools to select specific tools from each service,
keeping the total count under OpenAI's 128 tool limit.

Prerequisites:
    1. Install gws CLI:
        npm install -g @googleworkspace/cli

    2. Authenticate:
        gws auth setup

    3. Set environment variables:
        export OPENAI_API_KEY=your-openai-api-key
        export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_full.py
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

db = SqliteDb(db_file="tmp/workspace_full.db")

gws_env = {
    k: v
    for k, v in os.environ.items()
    if k.startswith("GOOGLE_WORKSPACE_CLI_") or k in ("HOME", "PATH", "USER")
}

# Expose all major Workspace services via MCP, but limit tools per service.
workspace_tools = MCPTools(
    command="gws mcp -s gmail,drive,calendar,sheets,docs",
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
        # Sheets
        "sheets_spreadsheets_get",
        "sheets_spreadsheets_values_get",
        "sheets_spreadsheets_values_update",
        # Docs
        "docs_documents_get",
        "docs_documents_create",
    ],
)

workspace_agent = Agent(
    id="workspace-full-agent",
    name="Workspace Assistant",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[workspace_tools],
    instructions=[
        "You are a full-featured Google Workspace assistant.",
        "All gws tools accept a 'params' object for path/query parameters.",
        "Every parameter (path and query) must go inside the params dict.",
        "To list messages: gmail_users_messages_list(params={'userId': 'me', 'maxResults': 5})",
        "To get a message: gmail_users_messages_get(params={'userId': 'me', 'id': '<messageId>', 'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']})",
        "Always use format='metadata' when reading messages to keep responses small.",
        "For Calendar, always pass params={'calendarId': 'primary'}.",
        "For Sheets, pass params={'spreadsheetId': '...'} and params={'range': 'Sheet1!A1:Z'}.",
        "For Docs, pass params={'documentId': '...'} to get a document.",
        "For multi-step tasks, plan your approach and execute step by step.",
        "Always confirm before sending emails, creating events, or modifying documents.",
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
    description="Full Google Workspace assistant via gws MCP",
    agents=[workspace_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="workspace_full:app", reload=True)
