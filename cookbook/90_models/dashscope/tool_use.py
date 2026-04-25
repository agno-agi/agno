"""
Dashscope Tool Use
==================

Cookbook example for `dashscope/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.dashscope import DashScope
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=DashScope(id="qwen-plus"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync + Streaming ---
    agent.print_response("What's happening in AI today?", stream=True)

    # --- Async + Streaming ---
    async def main():
        await agent.aprint_response(
            "What's the latest news about artificial intelligence?", stream=True
        )

    asyncio.run(main())
