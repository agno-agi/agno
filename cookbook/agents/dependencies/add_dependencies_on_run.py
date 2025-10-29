from agno.agent import Agent
from agno.models.openai import OpenAIChat


def get_user_profile(user_id: str = "john_doe") -> dict:
    """Get user profile information that can be referenced in responses.

    Args:
        user_id: The user ID to get profile for
    Returns:
        Dictionary containing user profile information
    """
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


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

# Example usage - sync
response = agent.run(
    "Please provide me with a personalized summary of today's priorities based on my profile and interests.",
    dependencies={
        "user_profile": get_user_profile,
        "current_context": get_current_context,
    },
    add_dependencies_to_context=True,
    debug_mode=True,
)

print(response.content)

# ------------------------------------------------------------
# ASYNC EXAMPLE
# ------------------------------------------------------------
# async def test_async():
#     async_response = await agent.arun(
#         "Based on my profile, what should I focus on this week? Include specific recommendations.",
#         dependencies={
#             "user_profile": get_user_profile,
#             "current_context": get_current_context
#         },
#         add_dependencies_to_context=True,
#         debug_mode=True,
#     )

#     print("\n=== Async Run Response ===")
#     print(async_response.content)

# # Run the async test
# import asyncio
# asyncio.run(test_async())

# ------------------------------------------------------------
# Print response EXAMPLE
# ------------------------------------------------------------
# agent.print_response(
#     "Please provide me with a personalized summary of today's priorities based on my profile and interests.",
#     dependencies={
#         "user_profile": get_user_profile,
#         "current_context": get_current_context,
#     },
#     add_dependencies_to_context=True,
#     debug_mode=True,
# )
