"""
Slack Context Provider
======================

SlackContextProvider wraps a read-only slice of agno's SlackTools and
gives the calling agent a single `query_<id>` tool. Send / upload /
download are explicitly disabled — this provider is for reading Slack
as context, not posting to it.

Under the hood the sub-agent orchestrates search_workspace /
get_channel_history / get_thread / get_user_info so the caller doesn't
have to drive those individually.

Requires:
    OPENAI_API_KEY
    SLACK_BOT_TOKEN  (bot token; xoxb-...)
                     With scopes: channels:read, channels:history,
                     search:read, users:read, users:read.email

    Optional:
    SLACK_TOKEN      (falls back here if SLACK_BOT_TOKEN isn't set)
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.slack import SlackContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider (token read from SLACK_BOT_TOKEN / SLACK_TOKEN)
# ---------------------------------------------------------------------------
slack = SlackContextProvider()

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=slack.get_tools(),
    instructions=slack.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\nslack.status() = {slack.status()}\n")
    prompt = "What's been discussed in the #general channel lately? Cite authors and timestamps."
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
