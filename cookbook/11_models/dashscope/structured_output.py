from typing import List

from agno.agent import Agent
from agno.models.dashscope import DashScope
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    name: str = Field(..., description="Give a name to this movie")
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
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ..., description="3 sentence storyline for the movie. Make it exciting!"
    )


# Agent that returns a structured output
structured_output_agent = Agent(
    model=DashScope(id="qwen-plus"),
    description="You write movie scripts and return them as structured JSON data.",
    output_schema=MovieScript,
)

structured_output_agent.print_response(
    "Create a movie script about llamas ruling the world. "
    "Return a JSON object with: name (movie title), setting, ending, genre, "
    "characters (list of character names), and storyline (3 sentences)."
)
