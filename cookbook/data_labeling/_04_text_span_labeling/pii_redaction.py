"""
Text Span Labeling - PII Redaction
==================================

Detect personally identifiable information and produce a redacted version
of the input. Same pattern as `basic.py`: model returns the exact substring
and its PII type; Python does the find-and-replace.
"""

from typing import List, Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class PIIItem(BaseModel):
    text: str = Field(..., description="Exact substring containing the PII")
    type: Literal["email", "phone", "ssn", "credit_card", "person_name"]


class PIIDetection(BaseModel):
    items: List[PIIItem]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Detect every span of personally identifiable information. For each item,
return the exact substring (preserving case and formatting) and its type.
Do not redact in your output - emit the raw text. Redaction happens in
post-processing.

Cover: email addresses, phone numbers, SSNs, credit card numbers, and full
person names. Skip generic references like "the customer".
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=PIIDetection,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def redact(text: str, items: List[PIIItem]) -> str:
    """Replace each detected span with a token of the form [TYPE]."""
    out = text
    for item in items:
        out = out.replace(item.text, f"[{item.type.upper()}]")
    return out


if __name__ == "__main__":
    text = (
        "Customer Jane Doe called from 415-555-0199 about her order. "
        "She asked us to email jane.doe@example.com with the receipt. "
        "Card on file ends 4242 4242 4242 4242."
    )
    run: RunOutput = agent.run(text)
    detection = run.content
    pprint({"detected": detection.items, "redacted": redact(text, detection.items)})
