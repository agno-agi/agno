"""
Text Classification - With Confidence
=====================================

Adds a per-prediction confidence field. Use when downstream consumers need
to route low-confidence labels to a human queue or to a stronger model.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    label: Literal["positive", "negative", "neutral"] = Field(
        ..., description="The assigned sentiment label"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Self-reported confidence in the label"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Classify the sentiment of the input text. Report a confidence level:
- high   - the sentiment is clear and unambiguous
- medium - the sentiment is mostly clear but with some hedging or mixed signals
- low    - the text is sarcastic, ambiguous, or off-topic
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "Best purchase of my life, life-changing!",
        "It's fine I guess.",
        "Yeah right, this thing is 'amazing'.",
    ]
    for text in samples:
        run: RunOutput = agent.run(text)
        pprint({"input": text, "result": run.content})
