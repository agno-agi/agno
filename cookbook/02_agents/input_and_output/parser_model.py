import random
from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


class NationalParkAdventure(BaseModel):
    park_name: str = Field(..., description="Name of the national park")
    best_season: str = Field(
        ...,
        description="Optimal time of year to visit this park (e.g., 'Late spring to early fall')",
    )
    signature_attractions: List[str] = Field(
        ...,
        description="Must-see landmarks, viewpoints, or natural features in the park",
    )
    recommended_trails: List[str] = Field(
        ...,
        description="Top hiking trails with difficulty levels (e.g., 'Angel's Landing - Strenuous')",
    )
    wildlife_encounters: List[str] = Field(
        ..., description="Animals visitors are likely to spot, with viewing tips"
    )
    photography_spots: List[str] = Field(
        ...,
        description="Best locations for capturing stunning photos, including sunrise/sunset spots",
    )
    camping_options: List[str] = Field(
        ..., description="Available camping areas, from primitive to RV-friendly sites"
    )
    safety_warnings: List[str] = Field(
        ..., description="Important safety considerations specific to this park"
    )
    hidden_gems: List[str] = Field(
        ..., description="Lesser-known spots or experiences that most visitors miss"
    )
    difficulty_rating: int = Field(
        ...,
        ge=1,
        le=5,
        description="Overall park difficulty for average visitor (1=easy, 5=very challenging)",
    )
    estimated_days: int = Field(
        ...,
        ge=1,
        le=14,
        description="Recommended number of days to properly explore the park",
    )
    special_permits_needed: List[str] = Field(
        default=[],
        description="Any special permits or reservations required for certain activities",
    )


agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    description="You help people plan amazing national park adventures and provide detailed park guides.",
    output_schema=NationalParkAdventure,
    parser_model=OpenAIChat(id="gpt-4o"),
)


# Get the response in a variable
national_parks = [
    "Yellowstone National Park",
    "Yosemite National Park",
    "Grand Canyon National Park",
    "Zion National Park",
    "Grand Teton National Park",
    "Rocky Mountain National Park",
    "Acadia National Park",
    "Mount Rainier National Park",
    "Great Smoky Mountains National Park",
    "Rocky National Park",
]
# Get the response in a variable
run: RunOutput = agent.run(national_parks[random.randint(0, len(national_parks) - 1)])
pprint(run.content)
