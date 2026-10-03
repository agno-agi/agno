"""
TogetherLink Structured Output
==============================

Cookbook example for `togetherlink/structured_output.py`.
"""

from typing import List

from agno.agent import Agent
from agno.models.togetherlink import TogetherLink
from pydantic import BaseModel, Field
from rich.pretty import pprint


class MovieScript(BaseModel):
    setting: str = Field(..., description="A nice setting for a blockbuster movie.")
    genre: str = Field(..., description="Genre of the movie.")
    name: str = Field(..., description="A name for this movie.")
    characters: List[str] = Field(..., description="Names of characters in the movie.")
    storyline: str = Field(..., description="3 sentence storyline for the movie.")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=TogetherLink(id="zai-org/GLM-5.3-Flash"),
    description="You write movie scripts based on a location.",
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = agent.run("New York")
    pprint(response.content)
