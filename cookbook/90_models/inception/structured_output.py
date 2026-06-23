"""
Inception Structured Output
===========================

Cookbook example for `inception/structured_output.py`.
"""

from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.inception import Inception
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

# ---------------------------------------------------------------------------
# Create Agent
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
        ..., description="3 sentence storyline for the movie. Make it exciting!"
    )


# Agent that uses JSON mode (recommended for Inception).
# Inception's OpenAI-compatible endpoint does not advertise native
# `json_schema` structured outputs, so use_json_mode=True is the reliable path.
json_mode_agent = Agent(
    model=Inception(id="mercury-2"),
    description="You write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)

# Agent that uses native structured outputs (output_schema without JSON mode).
structured_output_agent = Agent(
    model=Inception(id="mercury-2"),
    description="You write movie scripts.",
    output_schema=MovieScript,
)

# Get the response in a variable
# response: RunOutput = json_mode_agent.run("New York")
# pprint(response.content)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    json_mode_agent.print_response("New York")

    structured_output_agent.print_response("New York")
