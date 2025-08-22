import json

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIChat


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


# Create a Context-Aware Agent that can access real-time HackerNews data
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

# Example usage - sync
response = agent.run(
    "Summarize the top stories on HackerNews and identify any interesting trends.",
    dependencies={"top_hackernews_stories": get_top_hackernews_stories},
    add_dependencies_to_context=True,
    debug_mode=True,
)

print(response.content)

# ------------------------------------------------------------
# ASYNC EXAMPLE
# ------------------------------------------------------------
# async def test_async():
#     async_response = await agent.arun(
#         "What are the current trending topics based on the HackerNews data?",
#         dependencies={"hackernews_data": get_top_hackernews_stories},
#         add_dependencies_to_context=True,
#         debug_mode=True,
#     )

#     print("\n=== Async Run Response ===")
#     print(async_response.content)

# # Run the async test
# import asyncio
# asyncio.run(test_async())
