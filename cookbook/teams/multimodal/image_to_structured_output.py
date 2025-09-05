from typing import List

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIChat
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


image_analyst = Agent(
    name="Image Analyst",
    role="Analyze visual content and extract key elements",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Analyze images for visual elements, setting, and characters",
        "Focus on details that can inspire creative content",
    ],
)

script_writer = Agent(
    name="Script Writer",
    role="Create structured movie scripts from visual inspiration",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Transform visual analysis into compelling movie concepts",
        "Follow the structured output format precisely",
    ],
)

# Create a team for collaborative structured output generation
movie_team = Team(
    name="Movie Script Team",
    members=[image_analyst, script_writer],
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Create structured movie scripts from visual content.",
        "Image Analyst: First analyze the image for visual elements and context.",
        "Script Writer: Transform analysis into structured movie concepts.",
        "Ensure all output follows the MovieScript schema precisely.",
    ],
    output_schema=MovieScript,
)

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
