"""Run `uv pip install openai` to install dependencies."""

from pathlib import Path

from agno.agent import Agent
from agno.tools.dalle import DalleTools
from agno.utils.media import download_image

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Basic DALL-E agent with all functions enabled
agent = Agent(tools=[DalleTools(all=True)], name="DALL-E Image Generator")

# Example 2: Enable specific DALL-E functions
agent_specific = Agent(
    tools=[
        DalleTools(
            enable_create_image=True,
            model="gpt-image-2",
            size="1024x1024",
            quality="medium",
        )
    ],
    name="Basic DALL-E Generator",
)

# Example 3: High-quality custom DALL-E generator
custom_dalle = DalleTools(
    all=True, model="gpt-image-2", size="1536x1024", quality="high"
)

agent_custom = Agent(
    tools=[custom_dalle],
    name="Custom DALL-E Generator",
)

# Test basic generation

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Generate an image of a futuristic city with flying cars and tall skyscrapers",
        markdown=True,
    )

    response = agent_custom.run(
        "Create a panoramic nature scene showing a peaceful mountain lake at sunset",
        markdown=True,
    )
    output_path = Path(__file__).parent.joinpath("tmp/nature.png")
    if response.images and response.images[0].content:
        # GPT Image models return the image bytes directly
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.images[0].content)
    elif response.images and response.images[0].url:
        download_image(url=response.images[0].url, output_path=str(output_path))
