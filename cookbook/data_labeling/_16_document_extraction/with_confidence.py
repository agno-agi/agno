"""
Document Extraction - With Confidence
=====================================

Adds per-field confidence. Useful when input PDFs vary in quality (scans,
faxes, mixed languages) and downstream needs to route uncertain fields to
human review.
"""

from typing import Literal, Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.media import File
from agno.models.google import Gemini
from pydantic import BaseModel
from rich.pretty import pprint  # noqa

Confidence = Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ConfidentField(BaseModel):
    value: Optional[str] = None
    confidence: Confidence


class RecipeBook(BaseModel):
    title: ConfidentField
    cuisine: ConfidentField
    language: ConfidentField
    # Held as a string so per-field confidence applies cleanly to the count.
    recipe_count: ConfidentField


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Extract document metadata. For each field, report confidence:
- high   - explicit in the document
- medium - inferred from structure or context
- low    - guessed, partly obscured, or ambiguous

Be conservative. Mark unsure fields low.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3.5-flash"),
    instructions=instructions,
    output_schema=RecipeBook,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    run: RunOutput = agent.run(
        "Extract metadata with field-level confidence.", files=[File(url=url)]
    )
    pprint({"url": url, "result": run.content})
