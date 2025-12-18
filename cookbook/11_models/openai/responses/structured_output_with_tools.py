from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools
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


structured_output_agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    instructions="Use the tools to get the information you need. You have access to the DuckDuckGo search tools",
    description="You write movie scripts.",
    output_schema=MovieScript,
)

structured_output_agent.print_response("New York", stream=True)
