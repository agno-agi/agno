"""
Gemini Interactions - Deep Research streaming
==============================================

Stream real-time progress (thought summaries, text, generated images) from
a Deep Research task instead of waiting for the final report.

`thinking_summaries="auto"` is required to receive intermediate reasoning
during streaming; without it the stream may only deliver the final result.
Background execution is required for agents and is enabled automatically.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(
        agent="deep-research-preview-04-2026",
        thinking_summaries="auto",
    ),
    markdown=True,
)

if __name__ == "__main__":
    # --- Sync streaming ---
    agent.print_response(
        "Research the history and impact of Google TPUs.",
        stream=True,
    )

    # --- Async streaming ---
    asyncio.run(
        agent.aprint_response(
            "Research the current state of open-source LLM inference engines.",
            stream=True,
        )
    )
