"""
Openai Image Agent
==================

Cookbook example for `openai/responses/image_agent.py`.
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    tools=[WebSearchTools()],
    markdown=True,
)

agent.print_response(
    "Tell me about this image and give me the latest news about it.",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
    stream=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
