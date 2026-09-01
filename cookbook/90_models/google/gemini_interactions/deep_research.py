"""
Gemini Interactions - Deep Research
====================================

Run the Deep Research agent through the Gemini Interactions API.

Setting `agent` to a deep-research agent id switches GeminiInteractions to the
agent path (agent + agent_config) instead of the model path. The agent plans,
searches the web, and returns a researched report with citations.

Deep Research runs in the background; the model forces background execution
and the non-streaming path polls until the result is ready (can take minutes).

For the human-in-the-loop plan/refine/approve flow, see
deep_research_collaborative_planning.py.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(
        agent="deep-research-preview-04-2026",
        thinking_summaries="auto",
        visualization="auto",
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response(
        "Research the current state of solid-state battery commercialization "
        "and summarize the leading approaches."
    )

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "Compare the major open-source vector databases on indexing and query latency.",
            stream=True,
        )
    )
