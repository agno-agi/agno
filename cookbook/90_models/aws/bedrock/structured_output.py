"""
AWS Bedrock Structured Output
=============================

Demonstrates structured output (Pydantic models) with AWS Bedrock.

Uses tool-based extraction (forced tool call) to get structured JSON responses.

Run with:
    python cookbook/90_models/aws/bedrock/structured_output.py
"""

from typing import List

from agno.agent import Agent
from agno.models.aws import AwsBedrock
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    name: str = Field(..., description="Movie name")
    setting: str = Field(..., description="Setting for the movie")
    genre: str = Field(..., description="Genre (action, drama, comedy, etc.)")
    characters: List[str] = Field(..., description="Main characters")
    storyline: str = Field(..., description="Brief storyline (2-3 sentences)")


agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    description="You write creative movie scripts.",
    output_schema=MovieScript,
)


if __name__ == "__main__":
    agent.print_response("Write a movie set in Tokyo")
