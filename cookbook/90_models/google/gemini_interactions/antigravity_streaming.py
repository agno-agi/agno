"""
Gemini Interactions - Antigravity streaming
============================================

Stream the Antigravity agent's progress (tool calls, intermediate text,
generated artifacts) instead of waiting for the final result.

Antigravity runs in the foreground - the stream stays open for the duration
of the autonomous loop. No background reconnect is needed.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(
        agent="antigravity-preview-05-2026",
        environment="remote",
    ),
    markdown=True,
)

if __name__ == "__main__":
    # --- Sync streaming ---
    agent.print_response(
        "Read Hacker News, summarize the top 5 stories, and save the "
        "summary as a Markdown report.",
        stream=True,
    )

    # --- Async streaming ---
    asyncio.run(
        agent.aprint_response(
            "Find the three most-starred new Python repos on GitHub this "
            "week and write a one-paragraph blurb for each.",
            stream=True,
        )
    )
