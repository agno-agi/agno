"""
Dependencies In Context with List[Message] Input
=================================================

This example demonstrates that `add_dependencies_to_context=True` works
with all input types, including:
- String input (default)
- List[Message] input (used by AGUI interface)
- Single Message input
- List[Dict] input (alternative AGUI format)

Dependencies are injected into the last user message regardless of input type.
"""

import json

import httpx
from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai import OpenAIChat


def get_top_hackernews_stories(num_stories: int = 5) -> str:
    """Fetch and return the top stories from HackerNews.

    Args:
        num_stories: Number of top stories to retrieve (default: 5)
    Returns:
        JSON string containing story details (title, url, score, etc.)
    """
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


def get_current_user() -> dict:
    """Return current user info (simulated)."""
    return {
        "name": "Alice",
        "role": "Tech Lead",
        "interests": ["AI", "Python", "Startups"],
    }


# ---------------------------------------------------------------------------
# Create Agent with dependencies
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Dependencies are resolved when the agent runs (dependency injection for Agents)
    dependencies={
        "top_hackernews_stories": get_top_hackernews_stories,
        "current_user": get_current_user,
    },
    # This flag injects dependencies into the user message context
    add_dependencies_to_context=True,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent with different input types
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("Example 1: String input (existing behavior)")
    print("=" * 70)
    agent.print_response(
        "Based on my interests, which HackerNews stories would I find most interesting?",
        stream=True,
    )

    print("\n" + "=" * 70)
    print("Example 2: List[Message] input (used by AGUI interface)")
    print("=" * 70)
    # This input format is commonly used by AGUI and other chat interfaces
    # that maintain conversation history as a list of messages
    messages = [
        Message(role="user", content="Hi, I'm looking for tech news."),
        Message(role="assistant", content="I'd be happy to help you find tech news!"),
        Message(role="user", content="What HackerNews stories match my interests?"),
    ]
    agent.print_response(messages, stream=True)

    print("\n" + "=" * 70)
    print("Example 3: Single Message input")
    print("=" * 70)
    single_message = Message(
        role="user",
        content="Summarize the top stories and personalize recommendations for me.",
    )
    agent.print_response(single_message, stream=True)

    print("\n" + "=" * 70)
    print("Example 4: List[Dict] input (alternative AGUI format)")
    print("=" * 70)
    # Some interfaces pass messages as dicts instead of Message objects
    dict_messages = [
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there! How can I help?"},
        {"role": "user", "content": "Which stories should I read based on my profile?"},
    ]
    agent.print_response(dict_messages, stream=True)
