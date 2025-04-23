"""Serve a Playground app with an agent using structured outputs."""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
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


basic_agent = Agent(
    name="Agent with structured outputs",
    model=OpenAIChat(id="gpt-4o"),
    structured_outputs=True,
    response_model=MovieScript,
    markdown=True,
    # Notice: agents with structured output / response model won't stream answers
    stream=True,
)

app = Playground(
    agents=[
        basic_agent,
    ]
).get_app()

if __name__ == "__main__":
    serve_playground_app("structured_output:app", reload=True)
