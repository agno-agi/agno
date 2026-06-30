"""
Image To Structured Output
==========================

Demonstrates collaborative visual analysis with structured movie script output.
"""

from typing import List

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIResponses
from agno.team import Team
from pydantic import BaseModel, Field
from rich.pretty import pprint


class MovieScript(BaseModel):
    name: str = Field(..., description="Give a name to this movie")
    setting: str = Field(
        ..., description="Provide a nice setting for a blockbuster movie."
    )
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ..., description="3 sentence storyline for the movie. Make it exciting!"
    )


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
image_analyst = Agent(
    name="Image Analyst",
    role="Analyze visual content and extract key elements",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "Analyze images for visual elements, setting, and characters",
        "Focus on details that can inspire creative content",
    ],
)

script_writer = Agent(
    name="Script Writer",
    role="Create structured movie scripts from visual inspiration",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "Transform visual analysis into compelling movie concepts",
        "Follow the structured output format precisely",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
movie_team = Team(
    name="Movie Script Team",
    members=[image_analyst, script_writer],
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "Create structured movie scripts from visual content.",
        "Image Analyst: First analyze the image for visual elements and context.",
        "Script Writer: Transform analysis into structured movie concepts.",
        "Ensure all output follows the MovieScript schema precisely.",
    ],
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = movie_team.run(
        "Write a movie about this image",
        images=[
            Image(
                url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
            )
        ],
        stream=True,
    )

    for event in response:
        pprint(event.content)
