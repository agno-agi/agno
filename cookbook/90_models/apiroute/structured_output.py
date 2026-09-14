"""
API Route Structured Output
===========================

Cookbook example for `apiroute/structured_output.py`.
"""

from typing import List

from agno.agent import Agent
from agno.models.apiroute import ApiRoute
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


class MovieScript(BaseModel):
    setting: str = Field(..., description="The setting of the movie")
    protagonist: str = Field(..., description="Name of the protagonist")
    antagonist: str = Field(..., description="Name of the antagonist")
    plot: str = Field(..., description="The plot of the movie")
    genre: str = Field(..., description="The genre of the movie")
    scenes: List[str] = Field(..., description="List of scenes in the movie")


agent = Agent(
    model=ApiRoute(id="claude-3-7-sonnet-20250219"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
    markdown=True,
)

agent.print_response("Generate a movie script about a space exploration crew")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
