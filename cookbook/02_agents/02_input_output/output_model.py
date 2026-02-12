"""
Output Model
=============================

Use a separate model to parse unstructured output into a structured schema.
"""

from typing import List

from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint


class RecipeSummary(BaseModel):
    name: str = Field(..., description="Name of the recipe")
    cuisine: str = Field(..., description="Type of cuisine")
    difficulty: str = Field(..., description="Difficulty level: easy, medium, hard")
    ingredients: List[str] = Field(..., description="Key ingredients")
    time_minutes: int = Field(..., description="Total preparation and cooking time")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    description="You are a helpful chef that provides detailed recipe information.",
    # output_model uses a separate model to parse the main model's response
    # into a structured schema, unlike output_schema which constrains the main model
    output_model=OpenAIResponses(id="gpt-5.2-mini"),
    output_model_prompt="Extract the recipe details from the response into the schema.",
    output_schema=RecipeSummary,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run: RunOutput = agent.run("Give me a recipe for pad thai.")
    pprint(run.content)
