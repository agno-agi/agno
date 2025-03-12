from typing import List

from agno.agent import Agent, RunResponse  # noqa
from agno.models.openrouter import OpenRouter
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


# Agent that uses JSON mode
json_mode_agent = Agent(
    model=OpenRouter(id="gpt-4o"),
    description="You write movie scripts.",
    response_model=MovieScript,
)

# Agent that uses structured outputs
structured_output_agent = Agent(
    model=OpenRouter(id="gpt-4o-2024-08-06"),
    description="You write movie scripts.",
    response_model=MovieScript,
)


# Get the response in a variable
# json_mode_response: RunResponse = json_mode_agent.run("New York")
# pprint(json_mode_response.content)
# structured_output_response: RunResponse = structured_output_agent.run("New York")
# pprint(structured_output_response.content)

json_mode_agent.print_response("New York")
structured_output_agent.print_response("New York")
