"""
Azure OpenAI Responses API - Structured Output Example

This example demonstrates structured outputs using Azure OpenAI Responses API.

Required environment variables:
    AZURE_OPENAI_API_KEY: Your Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT: Your Azure OpenAI endpoint (e.g., https://your-resource.openai.azure.com/)
    AZURE_OPENAI_DEPLOYMENT: Your Azure deployment name
"""

from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.azure import AzureOpenAIResponses


class MovieScript(BaseModel):
    setting: str = Field(..., description="Provide a nice setting for a blockbuster movie.")
    ending: str = Field(..., description="Ending of the movie. If not available, provide a happy ending.")
    genre: str = Field(
        ..., description="Genre of the movie. If not available, select action, thriller or romantic comedy."
    )
    name: str = Field(..., description="Give a name to this movie")
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(..., description="3 sentence storyline for the movie. Make it exciting!")


agent = Agent(
    model=AzureOpenAIResponses(id="gpt-4o"),
    description="You are a Hollywood screenwriter.",
    response_model=MovieScript,
)

agent.print_response("Write a movie about robots taking over the world")
