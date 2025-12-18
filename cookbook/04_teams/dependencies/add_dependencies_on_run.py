from agno.models.openai import OpenAIChat
from agno.team import Team


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
    from datetime import datetime

    return {
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "PST",
        "day_of_week": datetime.now().strftime("%A"),
    }


team = Team(
    name="PersonalizationTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[],
    instructions=[
        "Analyze the user profile and current context to provide a personalized summary of today's priorities."
    ],
    markdown=True,
)

response = team.run(
    "Please provide me with a personalized summary of today's priorities based on my profile and interests.",
    dependencies={
        "user_profile": get_user_profile,
        "current_context": get_current_context,
    },
    add_dependencies_to_context=True,
)

print(response.content)
