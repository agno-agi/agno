"""
OpenAI Image Tools
==================

Demonstrates image generation with OpenAITools and GPT Image models.

Run `uv pip install openai` to install dependencies.
"""

from pathlib import Path

from agno.agent import Agent
from agno.tools.openai import OpenAITools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Basic image generation with only the image tool enabled
agent = Agent(
    tools=[OpenAITools(enable_transcription=False, enable_speech_generation=False)],
    name="Image Generator",
)

# Example 2: Custom size and quality
agent_custom = Agent(
    tools=[
        OpenAITools(
            enable_transcription=False,
            enable_speech_generation=False,
            image_model="gpt-image-2",
            image_size="1536x1024",
            image_quality="high",
        )
    ],
    name="Custom Image Generator",
)

# Example 3: Several images per call
agent_multi = Agent(
    tools=[
        OpenAITools(
            enable_transcription=False,
            enable_speech_generation=False,
            image_quality="low",
            image_n=2,
        )
    ],
    name="Multi Image Generator",
)


def save_images(response, name: str) -> None:
    """GPT Image models return image bytes, so write each one to tmp/."""
    for index, image in enumerate(response.images or []):
        if image.content:
            output_path = Path(__file__).parent.joinpath(f"tmp/{name}_{index}.png")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image.content)
            print(f"Saved {output_path}")


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
    save_images(response, "nature")

    response = agent_multi.run("Generate a simple icon of a red apple", markdown=True)
    save_images(response, "apple")
