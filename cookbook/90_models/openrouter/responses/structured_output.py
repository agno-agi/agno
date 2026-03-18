"""Structured output example using OpenRouter with the Responses API.

This demonstrates using Pydantic models for structured output with OpenRouter's
Responses API endpoint.

Requirements:
- Set OPENROUTER_API_KEY environment variable
"""

from typing import List

from agno.agent import Agent
from agno.models.openrouter import OpenRouterResponses
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


class MovieScript(BaseModel):
    name: str = Field(..., description="Give a name to this movie")
    setting: str = Field(
        ..., description="Provide a nice setting for a blockbuster movie."
    )
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
    )
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ..., description="3 sentence storyline for the movie. Make it exciting!"
    )


agent = Agent(
    model=OpenRouterResponses(id="openai/gpt-oss-20b", reasoning={"enabled": True}),
    description="You write movie scripts.",
    output_schema=MovieScript,
)

agent.print_response("New York")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
