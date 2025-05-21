
"""Run `pip install openai` to install dependencies."""

from pathlib import Path

from agno.agent import Agent
from agno.tools.dalle import DalleTools
from agno.utils.media import download_image

# Create an Agent with the DALL-E tool
agent = Agent(tools=[DalleTools()], name="DALL-E Image Generator")

# Example 1: Generate a basic image with default settings
agent.print_response(
    "Generate an image of a white furry cat sitting on a couch. What is the color of the cat?",
    markdown=True,
)

# agent.print_response(
#     "What is the color of the cat?",
#     markdown=True
# )
