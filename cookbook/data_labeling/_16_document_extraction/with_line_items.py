"""
Document Extraction - With Line Items
=====================================

Extract a nested list of sub-objects from a PDF. Same shape used for
invoice line items, statement transactions, contract clauses - the most
common production extraction pattern.
"""

from typing import List, Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.media import File
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Recipe(BaseModel):
    name: str = Field(..., description="Recipe name as printed")
    course: Optional[str] = Field(None, description="Appetizer, main, dessert, etc.")
    prep_time_minutes: Optional[int] = None


class RecipeBook(BaseModel):
    title: Optional[str] = None
    cuisine: Optional[str] = None
    recipes: List[Recipe] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Extract document metadata and every distinct recipe from the attached PDF.
Each recipe entry should reflect what the document actually shows; leave
fields null if not present. Do not invent recipes or paraphrase names.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=RecipeBook,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    run: RunOutput = agent.run(
        "Extract the book metadata and every recipe.", files=[File(url=url)]
    )
    pprint({"url": url, "result": run.content})
