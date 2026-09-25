"""
Live Tennis Tools
=============================

Demonstrates the Live Tennis API tools: live scores, match details, player
search, and upcoming fixtures across the ATP and WTA tours.

Requirements:
- A Live Tennis API key — get a free one (1,000 requests/day) at
  https://livetennisapi.com/subscribe/free

No extra packages are required (uses httpx, an agno core dependency).

Set the following environment variable (or pass api_key to LiveTennisTools directly):

    export LIVETENNISAPI_KEY="your_api_key"
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.livetennis import LiveTennisTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    name="Tennis Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[LiveTennisTools()],  # all functions are enabled by default
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Live scores, optionally filtered by tour
    agent.print_response("Which tennis matches are live right now on the ATP tour?")

    # Player search + profile
    agent.print_response("Find the player Carlos Alcaraz and show his profile")

    # Match details and score (the agent chains get_live_matches -> get_match_score)
    agent.print_response(
        "Get the current score of any live match and summarize it point by point"
    )

    # Upcoming fixtures
    agent.print_response("What are the next 5 upcoming tennis fixtures?")
