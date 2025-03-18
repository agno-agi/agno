import os
from typing import List

from agno.agent import Agent, RunResponse  # noqa
from agno.models.mistral import MistralChat
from agno.tools.duckduckgo import DuckDuckGoTools
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


structured_output_agent = Agent(
    model=MistralChat(
        id="mistral-large-latest",
    ),
    tools=[DuckDuckGoTools()],
    description="You help people write movie scripts.",
    response_model=MovieScript,
    show_tool_calls=True,
    # debug_mode=True,
)

# Get the response in a variable
structured_output_response: RunResponse = structured_output_agent.run("New York")
pprint(structured_output_response.content)

# json_mode_agent.print_response("Find a cool movie idea about London and write it.")
