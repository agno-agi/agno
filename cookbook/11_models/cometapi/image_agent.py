"""
Image analysis example using CometAPI with vision models.
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.cometapi import CometAPI

# Use a vision-capable model from CometAPI
agent = Agent(
    model=CometAPI(id="gpt-4o"),  # GPT-4o has vision capabilities
    markdown=True,
)

agent.print_response(
    "Describe this image in detail and tell me what you can see",
    images=[
        Image(
            url="https://httpbin.org/image/png"  # Reliable test image
        )
    ],
    stream=True,
)
