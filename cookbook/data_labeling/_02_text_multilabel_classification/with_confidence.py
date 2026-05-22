"""
Text Multilabel Classification - With Confidence
================================================

Adds per-tag confidence. Useful for downstream routing: low-confidence tags
can be flagged for human review while high-confidence ones land straight in
the training set.
"""

from typing import List, Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

Aspect = Literal["food", "service", "value", "atmosphere", "cleanliness"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Tag(BaseModel):
    aspect: Aspect
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence that the review actually addresses this aspect"
    )


class Tagging(BaseModel):
    tags: List[Tag]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Tag the review with every aspect the reviewer addresses. For each tag,
report confidence:
- high   - explicit, unambiguous mention
- medium - implicit or partial mention
- low    - inferred, hedged, or could be the reviewer just venting
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3.5-flash"),
    instructions=instructions,
    output_schema=Tagging,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "Pasta was excellent and the server brought refills without asking.",
        "Not sure I'd come back. Something was off.",
        "Cocktails were $22. The room is loud. Food was fine.",
    ]
    for text in samples:
        run: RunOutput = agent.run(text)
        pprint({"input": text, "result": run.content})
