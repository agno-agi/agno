"""
Sarvam Structured Output
========================

Get a typed Pydantic object back instead of free text. Sarvam supports native
`json_schema` structured outputs. `sarvam-105b` needs `reasoning_effort="none"`:
with the default reasoning, a schema request can spend the whole token budget on
reasoning and return `content: null`.
"""

from typing import List

from agno.agent import Agent
from agno.models.sarvam import Sarvam
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define the output schema
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
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Sarvam(id="sarvam-105b", reasoning_effort="none"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Write a movie script set in New York.")
