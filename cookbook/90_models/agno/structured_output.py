"""
Agno Gateway - structured output
================================

Get a typed, validated response by passing ``output_schema``. The gateway forwards a
``response_format`` json_schema to the underlying provider (native structured outputs),
the same path OpenAIChat uses. Set ``use_json_mode=True`` to fall back to JSON-object
mode for providers/models that do not support a strict schema.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.models.agno import Agno
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    name: str = Field(..., description="Give a name to this movie")
    setting: str = Field(..., description="A nice setting for a blockbuster movie.")
    genre: str = Field(..., description="Genre: action, thriller, or romantic comedy.")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(..., description="3 sentence storyline. Make it exciting!")


# Native structured outputs (default): the schema is sent as response_format json_schema.
structured_output_agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    description="You write movie scripts.",
    output_schema=MovieScript,
)

# JSON mode: the schema is injected into the prompt and the model returns a JSON object.
json_mode_agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    description="You write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Native structured output ---
    structured_output_agent.print_response("New York")

    # --- JSON mode ---
    json_mode_agent.print_response("Tokyo")

    # --- Async ---
    asyncio.run(structured_output_agent.aprint_response("London"))
