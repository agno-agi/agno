from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.litellm import LiteLLM
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


json_mode_agent = Agent(
    model=LiteLLM(id="gpt-4o"),
    description="You write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)

json_mode_agent.print_response("New York")
