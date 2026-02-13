"""
Image To Text
=============================

Image to Text Example.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Write a 3 sentence fiction story about the image",
        images=[Image(filepath=image_path)],
    )
