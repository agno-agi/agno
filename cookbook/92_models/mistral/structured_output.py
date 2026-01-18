from typing import List

from agno.agent import Agent, RunOutput  # noqa
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
    output_schema=MovieScript,
)

# Get the response in a variable
structured_output_response: RunOutput = structured_output_agent.run("New York")
pprint(structured_output_response.content)
