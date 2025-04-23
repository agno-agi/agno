"""🔧 Example: Using the OpenAITools Toolkit for Image Generation

This script demonstrates how to use the `OpenAITools` toolkit, which includes a tool for generating images using OpenAI's DALL-E within an Agno Agent.

Example prompts to try:
- "Create a surreal painting of a floating city in the clouds at sunset"
- "Generate a photorealistic image of a cozy coffee shop interior"
- "Design a cute cartoon mascot for a tech startup"
- "Create an artistic portrait of a cyberpunk samurai"

Run `pip install openai agno` to install the necessary dependencies.
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.openai import OpenAITools
from agno.utils.media import download_image

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[OpenAITools()],
    markdown=True,
    show_tool_calls=True,
)

response = agent.run(
    f"Generate a photorealistic image of a cozy coffee shop interior",
)

if response.images:
    download_image(response.images[0].url, Path("tmp/coffee_shop.png"))
