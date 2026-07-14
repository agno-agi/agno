"""
Cache Team Response
=============================

Demonstrates two-layer caching for team leader and member responses.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    role="Research and gather information",
    model=OpenAIResponses(id="gpt-5.2", cache_response=True),
)

writer = Agent(
    name="Writer",
    role="Write clear and engaging content",
    model=OpenAIResponses(id="gpt-5.2", cache_response=True),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
content_team = Team(
    members=[researcher, writer],
    model=OpenAIResponses(id="gpt-5.2", cache_response=True),
    markdown=True,
    debug_mode=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    content_team.print_response(
        "Write a very very very explanation of caching in software"
    )
