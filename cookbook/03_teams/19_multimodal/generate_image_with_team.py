"""
Generate Image With Team
========================

Demonstrates collaborative prompt optimization and DALL-E image generation.
"""

from typing import Iterator

from agno.agent import Agent, RunOutputEvent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.dalle import DalleTools
from agno.utils.common import dataclass_to_dict
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
image_generator = Agent(
    name="Image Creator",
    role="Generate images using DALL-E",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[DalleTools()],
    instructions=[
        "Use the DALL-E tool to create high-quality images",
        "Return image URLs in markdown format: `![description](URL)`",
    ],
)

prompt_engineer = Agent(
    name="Prompt Engineer",
    role="Optimize and enhance image generation prompts",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "Enhance user prompts for better image generation results",
        "Consider artistic style, composition, and technical details",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
image_team = Team(
    name="Image Generation Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[prompt_engineer, image_generator],
    instructions=[
        "Generate high-quality images from user prompts.",
        "Prompt Engineer: First enhance and optimize the user's prompt.",
        "Image Creator: Generate images using the enhanced prompt with DALL-E.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_stream: Iterator[RunOutputEvent] = image_team.run(
        "Create an image of a yellow siamese cat",
        stream=True,
        stream_events=True,
    )
    for chunk in run_stream:
        pprint(dataclass_to_dict(chunk, exclude={"messages"}))
        print("---" * 20)
