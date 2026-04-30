"""
Slack Search & Media Tools
==========================

Demonstrates SlackContextProvider with:

- **search_messages** — Search using the legacy API (works with user
  tokens `xoxp-`). Both bot and assisted read agents now have this
  enabled alongside `search_workspace`.
- **enable_media_tools** — Opt-in file handling:
  - `download_file` on read agents (fetch images/files for multimodal)
  - `upload_file` on write agent (post generated content)

This example uses Gemini as the sub-agent model for Slack operations,
while the outer agent uses a different model. This pattern is useful
when you want faster/cheaper tool calls but stronger reasoning on top.

Requires:
    GOOGLE_API_KEY
    SLACK_BOT_TOKEN  (xoxb-) — uses channel history, no search
    SLACK_TOKEN      (xoxp-) — enables search_messages API

With a bot token, search_messages returns `not_allowed_token_type` and
the agent falls back to get_channel_history. With a user token, both
search methods are available.

Usage:
    python cookbook/12_context/06_slack_search_media.py
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.slack import SlackContextProvider
from agno.models.google import Gemini

slack = SlackContextProvider(
    model=Gemini(id="gemini-3-flash-preview"),
    enable_media_tools=True,
)

agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    tools=slack.get_tools(),
    instructions=slack.instructions(),
    markdown=True,
)


async def main() -> None:
    print(f"slack.status() = {slack.status()}\n")

    search_prompt = "Search Slack for recent discussions about 'deployment'. Summarize the top 3 results."
    print(f"> {search_prompt}\n")
    await agent.aprint_response(search_prompt)


if __name__ == "__main__":
    asyncio.run(main())
