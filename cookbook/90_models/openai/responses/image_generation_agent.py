"""Example: Using the OpenAITools Toolkit for Image Generation

This script demonstrates how to use the `OpenAITools` toolkit, which includes a tool for generating images using OpenAI's GPT Image models within an Agno Agent.

Example prompts to try:
- "Create a surreal painting of a floating city in the clouds at sunset"
- "Generate a photorealistic image of a cozy coffee shop interior"
- "Design a cute cartoon mascot for a tech startup"
- "Create an artistic portrait of a cyberpunk samurai"

Run `uv pip install openai agno` to install the necessary dependencies.
"""

import base64

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.openai import OpenAITools
from agno.utils.media import save_base64_data

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[OpenAITools(image_model="gpt-image-2")],
    markdown=True,
)

response = agent.run(
    "Generate a photorealistic image of a cozy coffee shop interior",
)

if response.images and response.images[0].content:
    image_base64 = base64.b64encode(response.images[0].content).decode("utf-8")
    save_base64_data(image_base64, "tmp/coffee_shop.png")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
