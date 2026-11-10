"""
MiniMax Structured Output
=========================

Cookbook example for `minimax/structured_output.py`.
"""

from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.minimax import MiniMax
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


# MiniMax does not implement OpenAI-style native `response_format` /
# `json_schema`, so we drive structured output through JSON mode.
agent = Agent(
    model=MiniMax(id="MiniMax-M3"),
    description="You write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)

# Get the response in a variable
# response: RunOutput = agent.run("New York")
# pprint(response.content)

agent.print_response("New York")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
