from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.anthropic import Claude
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


class MovieScript(BaseModel):
    setting: str = Field(
        ..., description="Provide a nice setting for a blockbuster movie."
    )
    ending: str = Field(
        ...,
        description="Ending of the movie. If not available, provide a happy ending.",
    )
    genre: str = Field(
        ...,
        description="Genre of the movie. If not available, select action, thriller or romantic comedy.",
    )
    name: str = Field(..., description="Give a name to this movie")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ..., description="3 sentence storyline for the movie. Make it exciting!"
    )


movie_agent = Agent(
    model=Claude(id="claude-opus-4-5-20251101"),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
)

movie_agent.print_response("New York")

# You can also get the response in a variable:
# run: RunOutput = movie_agent.run("New York")
