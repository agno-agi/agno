"""
Text Span Labeling - Basic
==========================

Detect labeled substrings (entities) within a text. The model emits the
exact substring plus its type; offsets are computed in post-processing.

Asking the LLM to count characters is unreliable. Returning the literal
substring and locating it in Python is the robust pattern.
"""

from typing import List, Literal

from agno.agent import Agent, RunOutput  # noqa
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Entity(BaseModel):
    text: str = Field(..., description="Exact substring from the input")
    label: Literal["PERSON", "ORG", "LOCATION", "DATE"] = Field(
        ..., description="Entity type"
    )


class Entities(BaseModel):
    entities: List[Entity]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Extract all named entities from the input. For each entity, return the
exact substring as it appears in the text (case and punctuation preserved)
along with its label. Do not paraphrase or normalize. Do not include
pronouns or generic references.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=Entities,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def with_positions(text: str, entities: List[Entity]):
    """Find each entity's first occurrence offset; useful for downstream tagging."""
    for e in entities:
        start = text.find(e.text)
        end = start + len(e.text) if start >= 0 else None
        yield {"label": e.label, "text": e.text, "start": start, "end": end}


if __name__ == "__main__":
    text = (
        "On March 3rd, Sarah Johnson left Acme Corp to join a startup based in "
        "Berlin called Lumen Labs."
    )
    run: RunOutput = agent.run(text)
    pprint(list(with_positions(text, run.content.entities)))
