import asyncio
from typing import List

from agno.agent import Agent
from agno.models.ollama import Ollama
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
    model=Ollama(id="llama3.2"),
    description="You write movie scripts.",
    response_model=MovieScript,
    structured_outputs=True,
)

# Run the agent synchronously
structured_output_agent.print_response("Llamas ruling the world")


# Run the agent asynchronously
async def run_agents_async():
    await structured_output_agent.aprint_response("Llamas ruling the world")


asyncio.run(run_agents_async())
