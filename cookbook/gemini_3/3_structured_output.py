"""
Structured Output - Movie Critic with Typed Responses
=======================================================
Get typed Pydantic responses instead of free-form text.

Key concepts:
- output_schema: A Pydantic BaseModel defining the response structure
- response.content: The parsed Pydantic object (not a string)
- agent.run(): Returns a RunOutput with .content as your typed object
- Field(..., description=...): Descriptions guide the model on what to put in each field

Example prompts to try:
- "Review the movie Inception"
- "Review The Shawshank Redemption"
- "Review a recent sci-fi film"
"""

from typing import List

from agno.agent import Agent
from agno.models.google import Gemini
from pydantic import BaseModel, Field


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
    # output_schema forces the agent to return a MovieReview, not free text
    output_schema=MovieReview,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # agent.run() returns RunOutput; .content is the parsed Pydantic object
    run = critic_agent.run("Review the movie Inception")
    review: MovieReview = run.content

    print(f"Title: {review.title} ({review.year})")
    print(f"Rating: {review.rating}/10")
    print(f"Genre: {review.genre}")
    print("\nPros:")
    for pro in review.pros:
        print(f"  - {pro}")
    print("\nCons:")
    for con in review.cons:
        print(f"  - {con}")
    print(f"\nVerdict: {review.verdict}")

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Structured output is perfect for:

1. Building UIs
   review = agent.run("Review Inception").content
   render_movie_card(review)

2. Storing in databases
   db.insert("reviews", review.model_dump())

3. Comparing items
   inception = agent.run("Review Inception").content
   tenet = agent.run("Review Tenet").content
   if inception.rating > tenet.rating:
       print(f"{inception.title} wins")

4. Building pipelines
   movies = ["Inception", "Tenet", "Interstellar"]
   reviews = [agent.run(f"Review {m}").content for m in movies]

The schema guarantees you always get the fields you expect.
No parsing, no surprises.
"""
