import json

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team


def get_top_hackernews_stories(num_stories: int = 5) -> str:
    """Fetch and return the top stories from HackerNews.

    Args:
        num_stories: Number of top stories to retrieve (default: 5)
    Returns:
        JSON string containing story details (title, url, score, etc.)
    """
    # Get top stories
    stories = [
        {
            k: v
            for k, v in httpx.get(
                f"https://hacker-news.firebaseio.com/v0/item/{id}.json"
            )
            .json()
            .items()
            if k != "kids"  # Exclude discussion threads
        }
        for id in httpx.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        ).json()[:num_stories]
    ]
    return json.dumps(stories, indent=4)


def get_trending_topics() -> str:
    """Get trending tech topics."""
    return "AI, Machine Learning, Web Development, DevOps, Cybersecurity"


# Create Agents for the Team
news_agent = Agent(
    name="NewsAnalyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You analyze news trends and provide insights.",
)

trend_agent = Agent(
    name="TrendAnalyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You identify and analyze trending topics in technology.",
)

# Create a Team (no dependencies at instance level)
team = Team(
    name="AnalysisTeam",
    mode="coordinate",  # Use coordinate mode for simpler team behavior
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[news_agent, trend_agent],
    markdown=True,
)

# Example usage - Team with runtime dependencies (sync)
print("=== Team Run with Runtime Dependencies (Sync) ===")
response = team.run(
    "Based on the provided HackerNews data, summarize the current trending stories.",
    dependencies={"hackernews_stories": get_top_hackernews_stories},
    add_dependencies_to_context=True,
)

print(response.content)

# ------------------------------------------------------------
# ASYNC EXAMPLE
# ------------------------------------------------------------
# async def test_team_async():
#     print("\n=== Team Run with Runtime Dependencies (Async) ===")
#     async_response = await team.arun(
#         "Based on the provided topics, analyze the current technology trends.",
#         dependencies={"trending_topics": get_trending_topics},
#         add_dependencies_to_context=True,

#     )

#     print(async_response.content)

# # Run the async test
# import asyncio
# asyncio.run(test_team_async())
