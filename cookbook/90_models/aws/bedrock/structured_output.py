"""
AWS Bedrock Structured Output
=============================

Demonstrates structured output (Pydantic models) with AWS Bedrock.

The implementation automatically selects the optimal approach based on model:
- Claude 4.5+ (Sonnet 4.5, Haiku 4.5, Opus 4.5+): Uses native outputConfig.textFormat
- Claude 3.x and older: Uses tool-based fallback (forced tool call)

Both approaches return valid JSON matching the Pydantic schema.

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


# Claude 4.5+ uses native outputConfig for structured outputs
agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    description="You write creative movie scripts.",
    output_schema=MovieScript,
)


if __name__ == "__main__":
    agent.print_response("Write a movie set in Tokyo")
