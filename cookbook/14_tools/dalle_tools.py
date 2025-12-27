"""Run `pip install openai` to install dependencies."""

from pathlib import Path

from agno.agent import Agent
from agno.tools.dalle import DalleTools
from agno.utils.media import download_image

# Example 1: Basic DALL-E agent with all functions enabled
agent = Agent(tools=[DalleTools(all=True)], name="DALL-E Image Generator")

# Example 2: Enable specific DALL-E functions
agent_specific = Agent(
    tools=[
        DalleTools(
            enable_create_image=True,
            model="dall-e-3",
            size="1024x1024",
            quality="standard",
        )
    ],
    name="Basic DALL-E Generator",
)

# Example 3: High-quality custom DALL-E generator
custom_dalle = DalleTools(
    all=True, model="dall-e-3", size="1792x1024", quality="hd", style="natural"
)

agent_custom = Agent(
    tools=[custom_dalle],
    name="Custom DALL-E Generator",
)

# Test basic generation
agent.print_response(
    "Generate an image of a futuristic city with flying cars and tall skyscrapers",
    markdown=True,
)

response = agent_custom.run(
    "Create a panoramic nature scene showing a peaceful mountain lake at sunset",
    markdown=True,
)
if response.images and response.images[0].url:
    download_image(
        url=response.images[0].url,
        output_path=str(Path(__file__).parent.joinpath("tmp/nature.jpg")),
    )
