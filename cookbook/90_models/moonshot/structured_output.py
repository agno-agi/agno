"""
Moonshot Structured Output
==========================

Kimi can return structured data two ways, both driven by `output_schema`:

1. Native structured output - sends response_format={"type": "json_schema"} with your
   schema, and the API constrains the output to match it. This is the default and the
   one to reach for.
2. JSON mode - sends response_format={"type": "json_object"}, which guarantees valid
   JSON but not that it matches your schema. Opt in with `use_json_mode=True`.

Prefer native structured output. JSON mode is the fallback for models or schemas the
json_schema path does not accept, and it leans on field descriptions to convey the
shape, so keep them descriptive. Note that Kimi only emits JSON objects, never a
top-level JSON array - wrap lists in a field rather than asking for an array at the root.
"""

from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.moonshot import MoonShot
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
# Native structured output - the schema is enforced by the API
# ---------------------------------------------------------------------------

structured_output_agent = Agent(
    model=MoonShot(id="kimi-k3", reasoning_effort="low"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# JSON mode - valid JSON guaranteed, schema conformance is not
# ---------------------------------------------------------------------------

json_mode_agent = Agent(
    model=MoonShot(id="kimi-k3", reasoning_effort="low"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    structured_output_agent.print_response("New York")

    json_mode_agent.print_response("New York")
