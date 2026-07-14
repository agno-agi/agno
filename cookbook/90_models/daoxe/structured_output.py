"""
DaoXE Structured Output
=======================

Cookbook example for `daoxe/structured_output.py`.
"""

import os
from typing import List

from agno.agent import Agent
from agno.models.daoxe import DaoXE
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

model_id = os.environ.get("DAOXE_MODEL")
if not model_id:
    raise SystemExit(
        "Set DAOXE_MODEL to an exact model ID from your DaoXE account catalog "
        "(GET /v1/models)."
    )


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


structured_output_agent = Agent(
    model=DaoXE(id=model_id),
    description="You are a helpful assistant. Summarize the movie script based on the location in a JSON object.",
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    structured_output_agent.print_response("New York")
