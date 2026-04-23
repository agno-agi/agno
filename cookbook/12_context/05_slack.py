"""
Slack Context Provider
======================

SlackContextProvider exposes two tools to the calling agent:

- `query_<id>(question)` — read the workspace (search, channel
  history, threads, user / channel lookups)
- `update_<id>(instruction)` — post a message (resolves channel /
  user names, then calls `send_message` / `send_message_thread`)

Two sub-agents under the hood with minimal scopes: the read agent
never sees `send_message`, the write agent never sees
`search_workspace`. Uploads / downloads are off on both.

This cookbook always runs the read prompt. If you set
`SLACK_WRITE_CHANNEL` (e.g. `SLACK_WRITE_CHANNEL=#agno-test`), it
also runs a write prompt that posts a hello message there. Without
it, posting is skipped so a casual `python cookbook/12_context/05_slack.py`
never spams a real channel.

Requires:
    OPENAI_API_KEY
    SLACK_BOT_TOKEN  (bot token; xoxb-...)
                     With scopes: channels:read, users:read; add
                     chat:write to exercise the write path.

    Optional:
    SLACK_TOKEN         (falls back here if SLACK_BOT_TOKEN isn't set)
    SLACK_WRITE_CHANNEL (e.g. `#agno-test`) — opt in to the write demo
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.slack import SlackContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider (token read from SLACK_BOT_TOKEN / SLACK_TOKEN)
# ---------------------------------------------------------------------------
slack = SlackContextProvider(model=OpenAIResponses(id="gpt-5.4-mini"))

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=slack.get_tools(),
    instructions=slack.instructions(),
    markdown=True,
)


async def main() -> None:
    print(f"\nslack.status() = {slack.status()}\n")

    # --- Read path (always runs) ---
    # Uses `search_workspace`, which is paginated by relevance and
    # scales to huge workspaces — `list_channels` would page past
    # most of what's there.
    read_prompt = (
        "Find the 3 most recent messages in the #agents channel."
        "For each, author, and a one-line quote."
    )
    print(f"> {read_prompt}\n")
    await agent.aprint_response(read_prompt)

    # --- Write path (opt in via env) ---
    write_channel = "#agents"
    write_prompt = f"Post the message 'Hello from agno.context' to {write_channel}."
    print(f"\n> {write_prompt}\n")
    await agent.aprint_response(write_prompt)


if __name__ == "__main__":
    asyncio.run(main())
