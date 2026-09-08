"""
Aimlapi Image Agent
===================

Cookbook example for `aimlapi/image_agent.py`.
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.aimlapi import AIMLAPI

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=AIMLAPI(id="gpt-5.6-luna"),
    markdown=True,
)

agent.print_response(
    "Tell me about this image",
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
