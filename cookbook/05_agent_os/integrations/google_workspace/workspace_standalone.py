"""
Google Workspace Agent — Standalone (No AgentOS)
=================================================

Use gws MCP tools with a plain Agent, no server required.
Good for scripts, notebooks, and quick experiments.

Prerequisites:
    1. Install gws CLI:
        npm install -g @googleworkspace/cli

    2. Authenticate:
        gws auth setup

    3. Set environment variables:
        export OPENAI_API_KEY=your-openai-api-key
        export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_standalone.py
"""

import asyncio
import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
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


# Pass relevant env vars to the gws MCP subprocess.
# GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE lets gws find stored OAuth tokens.
GWS_ENV = {
    k: v
    for k, v in os.environ.items()
    if k.startswith("GOOGLE_WORKSPACE_CLI_") or k in ("HOME", "PATH", "USER")
}

# Common instructions for all gws-based agents.
# gws tools accept a 'params' object for path and query parameters.
GWS_INSTRUCTIONS = [
    "IMPORTANT: Every tool call MUST use the 'params' key. Never pass arguments at the top level.",
    "  gmail_users_messages_list(params={'userId': 'me', 'maxResults': 5})",
    "  gmail_users_messages_get(params={'userId': 'me', 'id': '<messageId>', 'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']})",
    "Always use format='metadata' when reading messages to keep responses small.",
]


async def main():
    # GWSTools requires async context management for stdio transport.
    # Use include_tools to limit which tools are registered (keeps context small).
    async with GWSTools(
        command="gws mcp -s gmail",
        env=GWS_ENV,
        include_tools=[
            "gmail_users_messages_list",
            "gmail_users_messages_get",
            "gmail_users_labels_list",
        ],
    ) as tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-4.1"),
            tools=[tools],
            instructions=[
                "You are a helpful Workspace assistant.",
                *GWS_INSTRUCTIONS,
                "Summarize results clearly and concisely.",
            ],
            add_datetime_to_context=True,
            markdown=True,
        )

        # Example queries — uncomment the one you want to try
        await agent.aprint_response("What are my latest 5 emails?")
        # await agent.aprint_response("What meetings do I have today?")
        # await agent.aprint_response("Find documents shared with me this week")


if __name__ == "__main__":
    asyncio.run(main())
