"""
Image To Text
=============================

Demonstrates collaborative image analysis and narrative generation.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
image_analyzer = Agent(
    name="Image Analyst",
    role="Analyze and describe images in detail",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "Analyze images carefully and provide detailed descriptions",
        "Focus on visual elements, composition, and key details",
    ],
)

creative_writer = Agent(
    name="Creative Writer",
    role="Create engaging stories and narratives",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "Transform image descriptions into compelling fiction stories",
        "Use vivid language and creative storytelling techniques",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
image_team = Team(
    name="Image Story Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[image_analyzer, creative_writer],
    instructions=[
        "Work together to create compelling fiction stories from images.",
        "Image Analyst: First analyze the image for visual details and context.",
        "Creative Writer: Transform the analysis into engaging fiction narratives.",
        "Ensure the story captures the essence and mood of the image.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    image_path = Path(__file__).parent.joinpath("sample.jpg")
    image_team.print_response(
        "Write a 3 sentence fiction story about the image",
        images=[Image(filepath=image_path)],
    )
