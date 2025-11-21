import asyncio
from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIChat
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


class TVShow(BaseModel):
    title: str = Field(..., description="TV show title")
    seasons: int = Field(..., description="Number of seasons")
    premise: str = Field(..., description="Show premise")


# Agent that uses structured outputs
structured_output_agent = Agent(
    model=OpenAIChat(id="gpt-4o-2024-08-06"),
    description="You write movie scripts.",
    output_schema=MovieScript,
)

# Agent that uses JSON mode
json_mode_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You write movie scripts.",
    output_schema=MovieScript,
    use_json_mode=True,
)


# Get the response in a variable
# json_mode_response: RunOutput = json_mode_agent.arun("New York")
# pprint(json_mode_response.content)
# structured_output_response: RunOutput = structured_output_agent.arun("New York")
# pprint(structured_output_response.content)

asyncio.run(structured_output_agent.aprint_response("New York"))
asyncio.run(json_mode_agent.aprint_response("New York"))

# Override output_schema for a single run
print(f"Schema before override: {structured_output_agent.output_schema.__name__}")
asyncio.run(structured_output_agent.aprint_response("New York", output_schema=TVShow))
print(f"Schema after override: {structured_output_agent.output_schema.__name__}")
