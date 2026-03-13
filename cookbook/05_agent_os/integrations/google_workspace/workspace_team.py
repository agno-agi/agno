"""
Google Workspace Team
=====================

A team of specialized agents, each handling a different Workspace service.
The coordinator routes user requests to the right specialist.

This pattern avoids tool count limits by splitting services across agents
and lets each agent have tailored instructions for its domain.

Prerequisites:
    1. Install gws CLI:
        npm install -g @googleworkspace/cli

    2. Authenticate:
        gws auth setup

    3. Set environment variables:
        export OPENAI_API_KEY=your-openai-api-key
        export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_team.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team
from agno.tools.mcp import MCPTools

# ---------------------------------------------------------------------------
# gws params fix (see workspace_agent.py for details)
# ---------------------------------------------------------------------------

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
# Shared config
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/workspace_team.db")
model = OpenAIChat(id="gpt-4.1")

gws_env = {
    k: v
    for k, v in os.environ.items()
    if k.startswith("GOOGLE_WORKSPACE_CLI_") or k in ("HOME", "PATH", "USER")
}

# ---------------------------------------------------------------------------
# Specialist Agents
# ---------------------------------------------------------------------------

gmail_agent = Agent(
    id="gmail-agent",
    name="Gmail Assistant",
    role="Email management specialist",
    model=model,
    tools=[GWSTools(command="gws mcp -s gmail", env=gws_env)],
    instructions=[
        "You handle all email-related tasks: reading, searching, composing, and managing labels.",
        "IMPORTANT: Every tool call MUST use the 'params' key. Never pass arguments at the top level.",
        "  gmail_users_messages_list(params={'userId': 'me', 'maxResults': 5})",
        "  gmail_users_messages_get(params={'userId': 'me', 'id': '<messageId>', 'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']})",
        "Always use format='metadata' when reading messages to keep responses small.",
        "Summarize emails concisely, highlighting sender, subject, and action items.",
        "Always confirm before sending or deleting emails.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

drive_agent = Agent(
    id="drive-agent",
    name="Drive Assistant",
    role="File management specialist",
    model=model,
    tools=[GWSTools(command="gws mcp -s drive", env=gws_env)],
    instructions=[
        "You handle all file and document tasks: searching, listing, uploading, and organizing files.",
        "IMPORTANT: Every tool call MUST use the 'params' key. Never pass arguments at the top level.",
        "  drive_files_list(params={'pageSize': 10})",
        "When listing files, show name, type, last modified date, and sharing status.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

calendar_agent = Agent(
    id="calendar-agent",
    name="Calendar Assistant",
    role="Scheduling specialist",
    model=model,
    tools=[GWSTools(command="gws mcp -s calendar", env=gws_env)],
    instructions=[
        "You handle all calendar tasks: viewing events, creating meetings, and finding free time.",
        "IMPORTANT: Every tool call MUST use the 'params' key. Never pass arguments at the top level.",
        "  calendar_events_list(params={'calendarId': 'primary', 'maxResults': 10})",
        "  calendar_events_get(params={'calendarId': 'primary', 'eventId': '<eventId>'})",
        "When showing events, include title, time, location, and attendees.",
        "Always confirm before creating, modifying, or deleting events.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

workspace_team = Team(
    id="workspace-team",
    name="Workspace Team",
    mode="coordinate",
    model=model,
    members=[gmail_agent, drive_agent, calendar_agent],
    instructions=[
        "You coordinate a team of Google Workspace specialists.",
        "Route email tasks to Gmail Assistant, file tasks to Drive Assistant, "
        "and scheduling tasks to Calendar Assistant.",
        "For cross-service requests (e.g., 'email the file John shared with me'), "
        "break the task into steps and delegate to the right specialists in order.",
    ],
    db=db,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    description="Google Workspace team with specialized agents",
    teams=[workspace_team],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="workspace_team:app", reload=True)
