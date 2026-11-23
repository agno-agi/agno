"""
Deepseek Structured Output
==========================

Cookbook example for `deepseek/structured_output.py`.
"""

from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.deepseek import DeepSeek
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


# Agent that uses JSON mode (recommended for DeepSeek).
# DeepSeek supports JSON mode (response_format={"type": "json_object"}) but not
# native/json_schema structured outputs, so use_json_mode=True is the reliable path.
json_mode_agent = Agent(
    model=DeepSeek(id="deepseek-v4-flash"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)

# Agent that uses native structured outputs (output_schema without JSON mode).
structured_output_agent = Agent(
    model=DeepSeek(id="deepseek-v4-flash"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    json_mode_agent.print_response("New York")

    structured_output_agent.print_response("New York")
