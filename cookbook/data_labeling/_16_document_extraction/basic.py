"""
Document Extraction - Basic
===========================

Extract top-level metadata from a multipage PDF into a typed object.
The schema here is for a recipe book - swap it for an Invoice, Contract,
LabReport, etc. for your domain.
"""

from typing import Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.media import File
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class RecipeBook(BaseModel):
    title: Optional[str] = Field(None, description="Book or document title")
    cuisine: Optional[str] = Field(None, description="Cuisine or culinary tradition")
    language: Optional[str] = Field(None, description="Language of the document")
    recipe_count: Optional[int] = Field(
        None, description="Number of distinct recipes in the document"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Extract document-level metadata from the attached PDF. Use exactly what
the document shows. If a field is not present, leave it null.
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
    run: RunOutput = agent.run("Extract document metadata.", files=[File(url=url)])
    pprint({"url": url, "result": run.content})
