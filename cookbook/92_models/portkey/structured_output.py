from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.portkey import Portkey
from pydantic import BaseModel, Field


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
    model=Portkey(id="@first-integrati-707071/gpt-5-nano"),
    output_schema=MovieScript,
    markdown=True,
)

# Get the response in a variable
# run: RunOutput = agent.run("New York")
# print(run.content)

agent.print_response("New York")
