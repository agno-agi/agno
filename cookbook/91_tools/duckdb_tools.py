"""
Duckdb Tools
=============================

Demonstrates duckdb tools.
"""

from agno.agent import Agent
from agno.tools.duckdb import DuckDbTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    tools=[DuckDbTools()],
    instructions="Use this file for Movies data: https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What is the average rating of movies?", markdown=True, stream=False
    )
