from agno.agent import Agent
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


profile_agent = Agent(
    name="ProfileAnalyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You analyze user profiles and provide personalized recommendations.",
)

context_agent = Agent(
    name="ContextAnalyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You analyze current context and timing to provide relevant insights.",
)

team = Team(
    name="PersonalizationTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[profile_agent, context_agent],
    dependencies={
        "user_profile": get_user_profile,
        "current_context": get_current_context,
    },
    add_dependencies_to_context=True,
    debug_mode=True,
    markdown=True,
)

response = team.run(
    "Please provide me with a personalized summary of today's priorities based on my profile and interests.",
)

print(response.content)

# ------------------------------------------------------------
# ASYNC EXAMPLE
# ------------------------------------------------------------
# async def test_async():
#     async_response = await team.arun(
#         "Based on my profile, what should I focus on this week? Include specific recommendations.",
#     )
#
#     print("\n=== Async Run Response ===")
#     print(async_response.content)

# # Run the async test
# import asyncio
# asyncio.run(test_async())
