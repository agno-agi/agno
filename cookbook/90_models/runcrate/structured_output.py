"""
Runcrate Structured Output
==========================

Cookbook example for `runcrate/structured_output.py`.
"""

from agno.agent import Agent
from agno.models.runcrate import Runcrate
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


class MovieScript(BaseModel):
    setting: str = Field(
        ...,
        description="Provide a nice setting for a blockbuster movie.",
    )
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description=(
            "Genre of the movie. If not available, select action, thriller or romantic"
            " comedy."
        ),
    )
    name: str = Field(..., description="Give a name to this movie")
    characters: list[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ...,
        description="3 sentence storyline for the movie. Make it exciting!",
    )


# Agent that uses a structured output
structured_output_agent = Agent(
    model=Runcrate(),
    description=(
        "You are a helpful assistant. Summarize the movie script based on the"
        " location in a JSON object."
    ),
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    structured_output_agent.print_response("New York")
