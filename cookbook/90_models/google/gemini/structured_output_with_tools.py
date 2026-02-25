"""
Google Structured Output with Tools
====================================

Cookbook example for using structured output (output_schema) together with
function tools on Gemini models.

Gemini 2.5 does not natively support combining JSON response mode with
function calling in the same request. Agno handles this automatically by
falling back to prompt-based JSON instructions while keeping tools active.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import Gemini
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schema + Tool
# ---------------------------------------------------------------------------


class MovieReview(BaseModel):
    title: str = Field(description="Title of the movie")
    year: int = Field(description="Release year of the movie")
    rating: int = Field(description="Rating out of 10")
    summary: str = Field(description="Brief summary of the review")


def get_movie_info(movie_title: str) -> str:
    """Look up release year and director for a movie."""
    movies = {
        "inception": "2010, directed by Christopher Nolan",
        "the matrix": "1999, directed by the Wachowskis",
        "interstellar": "2014, directed by Christopher Nolan",
    }
    return movies.get(movie_title.lower(), "Unknown movie")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    output_schema=MovieReview,
    tools=[get_movie_info],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Look up info about Inception, then write a review for it")

    # --- Sync + Streaming ---
    agent.print_response(
        "Look up info about Interstellar, then write a review for it", stream=True
    )

    # --- Async ---
    asyncio.run(
        agent.aprint_response(
            "Look up info about The Matrix, then write a review for it"
        )
    )

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "Look up info about The Matrix, then write a review for it", stream=True
        )
    )
