"""
Document Classification - Basic
===============================

Assign a single document-type label to a PDF. Use this as a coarse routing
step before a more specific extraction pipeline runs.
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


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Classify the attached PDF by document type. Use 'other' if it does not
fit any of the listed categories - do not force-fit. Base the decision
on the document's structure and content, not on a few keywords.
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
    run: RunOutput = agent.run("Classify this document.", files=[File(url=url)])
    pprint({"url": url, "result": run.content})
