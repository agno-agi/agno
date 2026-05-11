"""
AWS Bedrock Structured Output
=============================

Demonstrates structured output (Pydantic models) with AWS Bedrock.

The implementation automatically selects the optimal approach based on model:
- Claude 4.x (Sonnet 4.5, Haiku 4.5, Opus 4.5+): Uses native outputConfig.textFormat
- Claude 3.x and older: Uses tool-based fallback (forced tool call)

Both approaches return valid JSON matching the Pydantic schema.

Run with:
    python cookbook/90_models/aws/bedrock/structured_output.py
"""

from typing import List

from agno.agent import Agent
from agno.models.aws import AwsBedrock
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define Output Schema
# ---------------------------------------------------------------------------


class MovieScript(BaseModel):
    name: str = Field(..., description="Movie name")
    setting: str = Field(..., description="Setting for the movie")
    genre: str = Field(..., description="Genre (action, drama, comedy, etc.)")
    characters: List[str] = Field(..., description="Main characters")
    storyline: str = Field(..., description="Brief storyline (2-3 sentences)")


# ---------------------------------------------------------------------------
# Example 1: Claude 4.x - Uses native structured outputs
# ---------------------------------------------------------------------------

native_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    description="You write creative movie scripts.",
    output_schema=MovieScript,
)

# ---------------------------------------------------------------------------
# Example 2: Claude 3.x - Uses tool-based fallback
# ---------------------------------------------------------------------------

fallback_agent = Agent(
    model=AwsBedrock(id="us.anthropic.claude-3-5-haiku-20241022-v1:0"),
    description="You write creative movie scripts.",
    output_schema=MovieScript,
)


# ---------------------------------------------------------------------------
# Run examples
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Example 1: Claude 4.x with native structured output")
    print("=" * 60)
    print("(Uses outputConfig.textFormat for schema enforcement)")
    print()
    try:
        native_agent.print_response("Write a movie set in Tokyo")
    except Exception as e:
        print(f"Note: Claude 4.x may not be available yet: {e}")
    print()

    print("=" * 60)
    print("Example 2: Claude 3.x with tool-based fallback")
    print("=" * 60)
    print("(Uses forced tool call to extract structured data)")
    print()
    fallback_agent.print_response("Write a movie set in Paris")
