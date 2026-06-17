"""
Tzafon Structured Output
=========================

Cookbook example for `tzafon/structured_output.py`.

Demonstrates both structured output approaches:
- JSON mode (`use_json_mode=True`): the schema is described in the prompt.
- Native structured output (default): the schema is enforced by the model.
"""

from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.tzafon import Tzafon
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

# ---------------------------------------------------------------------------
# Output schema
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


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Agent that uses JSON mode
json_mode_agent = Agent(
    model=Tzafon(id="tzafon.sm-1"),
    description="You write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)

# Agent that uses native structured output
structured_output_agent = Agent(
    model=Tzafon(id="tzafon.sm-1"),
    description="You write movie scripts.",
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- JSON mode ---
    json_mode_agent.print_response("New York")

    # --- Native structured output ---
    structured_output_agent.print_response("New York")
