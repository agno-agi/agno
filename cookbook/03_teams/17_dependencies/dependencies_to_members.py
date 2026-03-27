"""
Dependencies To Members
=============================

Demonstrates passing dependencies on run and propagating them to member agents.
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def get_user_profile(user_id: str = "john_doe") -> dict:
    """Get user profile information that can be referenced in responses."""
    profiles = {
        "john_doe": {
            "name": "John Doe",
            "preferences": {
                "communication_style": "professional",
                "topics_of_interest": ["AI/ML", "Software Engineering", "Finance"],
                "experience_level": "senior",
            },
            "location": "San Francisco, CA",
            "role": "Senior Software Engineer",
        }
    }

    return profiles.get(user_id, {"name": "Unknown User"})


def get_current_context() -> dict:
    """Get current contextual information like time, weather, etc."""
    return {
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "PST",
        "day_of_week": datetime.now().strftime("%A"),
    }


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
profile_agent = Agent(
    name="ProfileAnalyst",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="You analyze user profiles and provide personalized recommendations.",
)

context_agent = Agent(
    name="ContextAnalyst",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="You analyze current context and timing to provide relevant insights.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="PersonalizationTeam",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[profile_agent, context_agent],
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response(
        "Please provide me with a personalized summary of today's priorities based on my profile and interests.",
        dependencies={
            "user_profile": get_user_profile,
            "current_context": get_current_context,
        },
        add_dependencies_to_context=True,
        debug_mode=True,
    )
