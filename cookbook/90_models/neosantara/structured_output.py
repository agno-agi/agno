"""
Neosantara Structured Output
============================

Cookbook example for `neosantara/structured_output.py`.
"""

from typing import List

from agno.agent import Agent
from agno.models.neosantara import Neosantara
from pydantic import BaseModel, Field

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


# Agent that uses structured outputs
agent = Agent(
    model=Neosantara(id="grok-4.1-fast-non-reasoning"),
    description="You write movie scripts. Respond ONLY with a valid JSON object matching the provided schema.",
    output_schema=MovieScript,
    use_json_mode=True,
)

# Print the response in the terminal
agent.print_response("New York")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
