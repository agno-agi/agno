"""
Text Classification - Basic
===========================

Assign one of a fixed set of labels to a piece of text. The simplest data
labeling primitive: input is a string, output is a label from a closed set.

This example classifies short product reviews into sentiment classes.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    label: Literal["positive", "negative", "neutral"] = Field(
        ..., description="The assigned sentiment label"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3.5-flash"),
    instructions="You classify product reviews by sentiment.",
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "I love this product, fantastic quality and fast shipping.",
        "Broken on arrival, total waste of money.",
        "It works as described, nothing special.",
    ]
    for text in samples:
        run: RunOutput = agent.run(text)
        pprint({"input": text, "result": run.content})
