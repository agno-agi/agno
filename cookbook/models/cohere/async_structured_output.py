import asyncio
from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.cohere import Cohere
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


agent = Agent(
    model=Cohere(
        id="command-a-03-2025",
    ),
    description="You help people write movie scripts.",
    output_schema=MovieScript,
)

# Get the response in a variable
# response: RunOutput = await agent.arun("New York")
# pprint(response.content)

asyncio.run(agent.aprint_response("Find a cool movie idea about London and write it."))
