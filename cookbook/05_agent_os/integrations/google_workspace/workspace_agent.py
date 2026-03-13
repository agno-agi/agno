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
# gws params fix
# ---------------------------------------------------------------------------
# gws MCP tools accept all path/query parameters inside a 'params' dict,
# but models sometimes pass them at the top level or omit required params.
# GWSTools auto-wraps stray args into params and injects sensible defaults.

KNOWN_GWS_KEYS = {"params", "body", "page_all", "upload"}

# Default params injected when the model omits required path parameters.
GWS_DEFAULT_PARAMS: dict = {
    "gmail_users_messages_list": {"userId": "me"},
    "gmail_users_messages_get": {"userId": "me", "format": "metadata"},
    "gmail_users_messages_send": {"userId": "me"},
    "gmail_users_labels_list": {"userId": "me"},
    "calendar_events_list": {"calendarId": "primary"},
    "calendar_events_get": {"calendarId": "primary"},
    "calendar_events_insert": {"calendarId": "primary"},
}


def _make_pre_hook(tool_name: str):
    """Create a pre-hook for *tool_name* that normalises arguments."""
    defaults = GWS_DEFAULT_PARAMS.get(tool_name, {})

    def hook(fc):
        args = fc.arguments or {}

        # 1. Wrap stray top-level keys into params
        if "params" not in args:
            stray = {k: v for k, v in args.items() if k not in KNOWN_GWS_KEYS}
            if stray:
                kept = {k: v for k, v in args.items() if k in KNOWN_GWS_KEYS}
                kept["params"] = stray
                args = kept

        # 2. Ensure defaults are present
        if defaults:
            params = args.get("params", {})
            for k, v in defaults.items():
                params.setdefault(k, v)
            args["params"] = params

        fc.arguments = args

    return hook


class GWSTools(MCPTools):
    """MCPTools subclass that auto-fixes the params pattern for gws CLI tools."""

    async def build_tools(self):
        await super().build_tools()
        for name, fn in self.functions.items():
            fn.pre_hook = _make_pre_hook(name)


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
workspace_tools = GWSTools(
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
    model=OpenAIChat(id="gpt-4.1"),
    db=db,
    tools=[workspace_tools],
    instructions=[
        "You are a personal workspace assistant with access to Gmail, Google Drive, and Google Calendar.",
        "IMPORTANT: Every tool call MUST use the 'params' key. Never pass arguments at the top level.",
        "Examples of correct tool calls:",
        "  gmail_users_messages_list(params={'userId': 'me', 'maxResults': 5})",
        "  gmail_users_messages_get(params={'userId': 'me', 'id': '<messageId>', 'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']})",
        "  calendar_events_list(params={'calendarId': 'primary', 'maxResults': 10})",
        "  calendar_events_get(params={'calendarId': 'primary', 'eventId': '<eventId>'})",
        "  drive_files_list(params={'pageSize': 10})",
        "Always use format='metadata' when reading Gmail messages to keep responses small.",
        "Always summarize results clearly and highlight actionable items.",
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
