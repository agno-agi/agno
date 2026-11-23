"""
Xiaomi MiMo Structured Output
=============================

Get a typed Pydantic object back instead of free text. MiMo supports JSON mode
(`response_format={"type": "json_object"}`) but not native json_schema structured
outputs, so pass `use_json_mode=True` alongside `output_schema`.
"""

from typing import List

from agno.agent import Agent
from agno.models.xiaomi import MiMo
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

# MiMo does not support native json_schema structured outputs, so use JSON mode.
jsonagent = Agent(
    model=MiMo(id="mimo-v2.5-pro"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)
structureagent = Agent(
    model=MiMo(id="mimo-v2.5-pro"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    jsonagent.print_response("New York")
    structureagent.print_response("New York")
