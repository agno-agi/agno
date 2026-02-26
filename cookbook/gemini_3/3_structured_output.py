"""
3. Structured Output
====================
Get structured, typed responses using Pydantic models.
Instead of free-form text, the agent returns data you can use in code.

Run:
    python cookbook/gemini_3/3_structured_output.py

Example prompt:
    "Review the movie Inception"
"""

from typing import List

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.google import Gemini


# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------
class MovieReview(BaseModel):
    title: str = Field(..., description="Movie title")
    year: int = Field(..., description="Release year")
    rating: float = Field(..., ge=0, le=10, description="Rating out of 10")
    genre: str = Field(..., description="Primary genre")
    pros: List[str] = Field(..., description="What works well")
    cons: List[str] = Field(..., description="What could be better")
    verdict: str = Field(..., description="One-sentence final verdict")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
critic_agent = Agent(
    name="Movie Critic",
    model=Gemini(id="gemini-3.1-pro-preview"),
    instructions="You are a professional movie critic. Provide balanced, thoughtful reviews.",
    output_schema=MovieReview,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run = critic_agent.run("Review the movie Inception")
    review: MovieReview = run.content
    print(f"Title: {review.title} ({review.year})")
    print(f"Rating: {review.rating}/10")
    print(f"Genre: {review.genre}")
    print(f"\nPros:")
    for pro in review.pros:
        print(f"  - {pro}")
    print(f"\nCons:")
    for con in review.cons:
        print(f"  - {con}")
    print(f"\nVerdict: {review.verdict}")
