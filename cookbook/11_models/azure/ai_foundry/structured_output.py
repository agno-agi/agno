from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.azure import AzureAIFoundry
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


# Agent that uses structured outputs with strict_output=True (default)
structured_output_agent = Agent(
    model=AzureAIFoundry(id="gpt-4o"),
    description="You write movie scripts.",
    output_schema=MovieScript,
)


# Agent with strict_output=False (guided mode)
# strict_output=False: Attempts to follow the schema as a guide but may occasionally deviate
guided_output_agent = Agent(
    model=AzureAIFoundry(id="gpt-4o", strict_output=False),
    description="You write movie scripts.",
    output_schema=MovieScript,
)


# Get the response in a variable
# structured_output_response: RunOutput = structured_output_agent.run("New York")
# pprint(structured_output_response.content)


structured_output_agent.print_response("New York")
guided_output_agent.print_response("New York")
