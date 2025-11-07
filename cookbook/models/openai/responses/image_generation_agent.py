"""🔧 Example: Using the OpenAITools Toolkit for Image Generation

This script demonstrates how to use the `OpenAITools` toolkit, which includes a tool for generating images using OpenAI's DALL-E within an Agno Agent.

Example prompts to try:
- "Create a surreal painting of a floating city in the clouds at sunset"
- "Generate a photorealistic image of a cozy coffee shop interior"
- "Design a cute cartoon mascot for a tech startup"
- "Create an artistic portrait of a cyberpunk samurai"

Run `pip install openai agno` to install the necessary dependencies.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.openai import OpenAITools
from agno.utils.media import save_base64_data

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[OpenAITools(image_model="gpt-image-1")],
    markdown=True,
)

response = agent.run(
    "Generate a photorealistic image of a cozy coffee shop interior",
)

if response.images and response.images[0].content:
    save_base64_data(str(response.images[0].content), "tmp/coffee_shop.png")
