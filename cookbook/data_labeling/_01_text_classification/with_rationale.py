"""
Text Classification - With Rationale
====================================

Adds a short rationale explaining the label. Useful for auditability and
for training datasets where the reasoning trace is itself an artifact.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    label: Literal["positive", "negative", "neutral"] = Field(
        ..., description="The assigned sentiment label"
    )
    rationale: str = Field(
        ..., description="One sentence explaining why this label was chosen"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Classify the sentiment of the input text. Quote or paraphrase the specific
words that drove your decision in the rationale.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "Shipping was fast but the product itself fell apart in a week.",
        "Better than expected, will buy again.",
    ]
    for text in samples:
        run: RunOutput = agent.run(text)
        pprint({"input": text, "result": run.content})
