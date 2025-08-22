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


# Create Agents for the Team
news_agent = Agent(
    name="NewsAnalyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a tech news analyst specializing in HackerNews trends.",
)

summary_agent = Agent(
    name="SummaryAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You create concise summaries and extract key insights.",
)

# Create a Team with dependencies set at instance level
team = Team(
    name="NewsTeam",
    mode="coordinate",  # Use coordinate mode for simpler team behavior
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[news_agent, summary_agent],
    # Dependencies are set at the Team instance level and resolved automatically
    dependencies={"top_hackernews_stories": get_top_hackernews_stories},
    # Enable context addition at instance level
    add_dependencies_to_context=True,
    markdown=True,
)

# Example usage - Team with instance dependencies
print("=== Team with Instance Dependencies ===")
team.print_response(
    "Based on the provided HackerNews data, analyze trends and provide insights.",
    stream=True,
)
