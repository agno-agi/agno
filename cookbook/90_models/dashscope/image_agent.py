"""
Dashscope Image Agent
=====================

Cookbook example for `dashscope/image_agent.py`.
"""

import asyncio

from agno.agent import Agent
from agno.media import Image
from agno.models.dashscope import DashScope
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=DashScope(id="qwen-vl-plus"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync + Streaming ---
    agent.print_response(
        "Analyze this image in detail and tell me what you see. Also search for more information about the subject.",
        images=[
            Image(
                url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
            )
        ],
        stream=True,
    )

    # --- Async + Streaming ---
    async def main():
        await agent.aprint_response(
            "What do you see in this image? Provide a detailed description and search for related information.",
            images=[
                Image(
                    url="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/1200px-Cat03.jpg"
                )
            ],
            stream=True,
        )

    asyncio.run(main())
