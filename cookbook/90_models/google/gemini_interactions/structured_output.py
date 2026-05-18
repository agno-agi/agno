"""
Gemini Interactions - Structured Output
========================================

Example showing structured output with the Interactions API.
Uses Pydantic models to enforce JSON schema on responses.
"""

from agno.agent import Agent
from agno.models.google import GeminiInteractions
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define output schema
# ---------------------------------------------------------------------------


class MovieReview(BaseModel):
    title: str = Field(description="The movie title")
    year: int = Field(description="Release year")
    genre: str = Field(description="Primary genre")
    rating: float = Field(description="Rating out of 10")
    summary: str = Field(description="Brief review summary")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(id="gemini-3-flash-preview"),
    output_schema=MovieReview,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = agent.run("Write a review of The Matrix (1999)")

    if response.content:
        # When using output_schema, the framework parses the response into
        # the Pydantic model automatically. response.content is a MovieReview object.
        review = response.content
        if isinstance(review, MovieReview):
            print(f"Title: {review.title}")
            print(f"Year: {review.year}")
            print(f"Genre: {review.genre}")
            print(f"Rating: {review.rating}/10")
            print(f"Summary: {review.summary}")
        else:
            print(f"Raw response: {review}")
