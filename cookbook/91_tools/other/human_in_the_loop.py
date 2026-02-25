"""Human-in-the-Loop: Adding User Confirmation to Tool Calls

This example shows how to implement human-in-the-loop functionality in your Agno tools.
It shows how to:
- Add pre-hooks to tools for user confirmation
- Handle user input during tool execution
- Gracefully cancel operations based on user choice

Some practical applications:
- Confirming sensitive operations before execution
- Reviewing API calls before they're made
- Validating data transformations
- Approving automated actions in critical systems

Run `uv pip install openai httpx rich agno` to install dependencies.
"""

import json
from typing import Iterator

import httpx
from agno.agent import Agent
from agno.exceptions import StopAgentRun
from agno.models.openai import OpenAIChat
from agno.tools import FunctionCall, tool
from rich.console import Console

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# This is the console instance used by the print_response method
# We can use this to stop and restart the live display and ask for user confirmation
console = Console()


def pre_hook(fc: FunctionCall):
    """Pre-hook that asks for user confirmation before running a tool."""
    print(f"\n⚠️  About to run: {fc.function.name}")
    print(f"   Arguments: {fc.arguments}")

    message = input("Do you want to continue? [y/n] (default: y): ").strip().lower()

    if message == "n":
        raise StopAgentRun(
            "Tool call cancelled by user",
            agent_message="Stopping execution as permission was not granted.",
        )


@tool(pre_hook=pre_hook)
def get_top_hackernews_stories(num_stories: int) -> Iterator[str]:
    """Fetch top stories from Hacker News.

    Args:
        num_stories (int): Number of stories to retrieve

    Returns:
        str: JSON string containing story details
    """
    # Fetch top story IDs
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()

    # Yield story details
    for story_id in story_ids[:num_stories]:
        story_response = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        )
        story = story_response.json()
        if "text" in story:
            story.pop("text", None)
        yield json.dumps(story)


# Initialize the agent
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_top_hackernews_stories],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Fetch the top 2 hackernews stories?", stream=True, console=console
    )
