"""
Copilot Structured Output
=========================

Cookbook example for GitHub Copilot model provider with structured output.
"""

from typing import List

from agno.agent import Agent
from agno.models.copilot import CopilotChat
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class MovieScript(BaseModel):
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
    name: str = Field(..., description="Give a name to this movie")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ...,
        description="3 sentence storyline for the movie. Make it exciting!",
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=CopilotChat(id="gpt-4.1"),
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("New York")
