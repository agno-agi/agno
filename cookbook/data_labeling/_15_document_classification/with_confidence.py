"""
Document Classification - With Confidence
=========================================

Adds confidence so downstream routing can treat low-confidence documents
differently (escalate, retry, or send to human review).
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.media import File
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    label: Literal[
        "invoice",
        "receipt",
        "contract",
        "spec_sheet",
        "report",
        "recipe",
        "other",
    ] = Field(..., description="Document type")
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence in the label"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Classify the attached PDF and report confidence:
- high   - document is unambiguously of this type (clear structure, headings)
- medium - mostly clear but with mixed signals (e.g. a contract that
           includes an embedded invoice)
- low    - could fit several categories; pick the closest and flag low
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
    url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    run: RunOutput = agent.run(
        "Classify this document with confidence.", files=[File(url=url)]
    )
    pprint({"url": url, "result": run.content})
