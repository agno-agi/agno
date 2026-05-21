"""
Text Extraction - With Confidence
=================================

Adds per-field confidence using a shared `ConfidentField` wrapper. Use when
downstream consumers need to route low-confidence fields to a human queue
or a stronger model.
"""

from typing import Literal, Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ConfidentField(BaseModel):
    value: Optional[str] = None
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence in the extracted value"
    )


class Contact(BaseModel):
    name: ConfidentField
    email: ConfidentField
    phone: ConfidentField
    company: ConfidentField
    title: ConfidentField


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Extract contact information from the input. For each field:
- value:      what the text shows; null if the field is missing
- confidence: high if explicit and unambiguous;
              medium if implied or partially formatted;
              low if guessed or ambiguous

Use exactly what the text shows. Do not normalize or paraphrase.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3.5-flash"),
    instructions=instructions,
    output_schema=Contact,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "Sarah Johnson, VP of Marketing at Acme Corp. sarah@acme.com / +1-555-0102.",
        "ping @mike on the eng team",
    ]
    for text in samples:
        run: RunOutput = agent.run(text)
        pprint({"input": text, "result": run.content})
