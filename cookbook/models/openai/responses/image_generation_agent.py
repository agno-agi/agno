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

openai_tools: OpenAITools = OpenAITools()

# Create a simple agent using the GPT-4o model and the OpenAI toolkit
agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[openai_tools],
    markdown=True,
)

# Ask the agent to generate an image using the tool
agent.print_response(
    f"Generate an image of a futuristic cityscape at sunset painted in the style of Van Gogh. Use the default   size."
)
