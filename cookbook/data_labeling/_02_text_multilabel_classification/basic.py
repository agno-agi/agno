"""
Text Multilabel Classification - Basic
======================================

Assign any subset of a fixed tag set to a piece of text. Multiple tags may
apply to the same input.

This example tags restaurant reviews by which aspects the reviewer commented
on.
"""

from typing import List, Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

Aspect = Literal["food", "service", "value", "atmosphere", "cleanliness"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Tagging(BaseModel):
    tags: List[Aspect] = Field(
        ..., description="All aspects the reviewer commented on; empty if none"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Tag the review with every aspect the reviewer commented on. Include an
aspect only when the text actually addresses it. An aspect can be mentioned
positively or negatively - both count.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=Tagging,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "Pasta was excellent and our server was attentive. A bit pricey but worth it.",
        "Place was filthy. Floors sticky, bathroom unusable.",
        "Came for the vibes, stayed for the cocktails. The space is gorgeous.",
    ]
    for text in samples:
        run: RunOutput = agent.run(text)
        pprint({"input": text, "result": run.content})
