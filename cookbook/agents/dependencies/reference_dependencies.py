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
    # Each function in the dependencies is resolved when the agent is run,
    # think of it as dependency injection for Agents
    dependencies={"top_hackernews_stories": get_top_hackernews_stories},
    instructions=[
        "You are an insightful tech trend observer! 📰",
        "Here are the top stories on HackerNews: {top_hackernews_stories}",
    ],
    markdown=True,
)

# Example usage
agent.print_response(
    "Summarize the top stories on HackerNews and identify any interesting trends.",
    stream=True,
)
