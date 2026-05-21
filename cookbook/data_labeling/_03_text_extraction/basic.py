"""
Text Extraction - Basic
=======================

Extract typed structured data from free-form text. The output is a Pydantic
object whose schema you control.

This example extracts contact info from an email signature.
"""

from typing import Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Contact(BaseModel):
    name: Optional[str] = Field(None, description="Full name as written")
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number, raw format")
    company: Optional[str] = Field(None, description="Company or organization")
    title: Optional[str] = Field(None, description="Job title")


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Extract contact information from the input. Use exactly what the text shows
- do not normalize or reformat. If a field is missing, leave it null. Do
not guess.
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
        "Hi - Sarah Johnson, VP of Marketing at Acme Corp. "
        "sarah@acme.com / +1-555-0102.",
        "regards, Mike (engineering@startup.io)",
    ]
    for text in samples:
        run: RunOutput = agent.run(text)
        pprint({"input": text, "result": run.content})
