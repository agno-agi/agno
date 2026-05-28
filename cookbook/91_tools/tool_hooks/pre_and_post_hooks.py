"""
Pre And Post Hooks
=============================

Demonstrates pre and post hooks.
"""

import asyncio
import json
from typing import AsyncIterator, Iterator

import httpx
from agno.agent import Agent
from agno.tools import FunctionCall, tool

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def pre_hook(fc: FunctionCall):
    print(f"Pre-hook: {fc.function.name}")
    print(f"Arguments: {fc.arguments}")
    print(f"Result: {fc.result}")


def post_hook(fc: FunctionCall):
    print(f"Post-hook: {fc.function.name}")
    print(f"Arguments: {fc.arguments}")
    print(f"Result: {fc.result}")


@tool(pre_hook=pre_hook, post_hook=post_hook)
def get_top_hackernews_stories(agent: Agent) -> Iterator[str]:
    num_stories = agent.dependencies.get("num_stories", 5) if agent.dependencies else 5

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


agent = Agent(
    dependencies={
        "num_stories": 2,
    },
    tools=[get_top_hackernews_stories],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Async Variant
# ---------------------------------------------------------------------------


async def pre_hook_async(fc: FunctionCall):
    print(f"About to run: {fc.function.name}")


async def post_hook_async(fc: FunctionCall):
    print("After running: ", fc.function.name)


@tool(show_result=True, pre_hook=pre_hook_async, post_hook=post_hook_async)
async def get_top_hackernews_stories_async(agent: Agent) -> AsyncIterator[str]:
    num_stories = agent.dependencies.get("num_stories", 5) if agent.dependencies else 5

    async with httpx.AsyncClient() as client:
        # Fetch top story IDs
        response = await client.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json"
        )
        story_ids = response.json()

        # Yield story details
        for story_id in story_ids[:num_stories]:
            story_response = await client.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            )
            story = story_response.json()
            if "text" in story:
                story.pop("text", None)
            yield json.dumps(story)


async_agent = Agent(
    dependencies={
        "num_stories": 2,
    },
    tools=[get_top_hackernews_stories_async],
    markdown=True,
)
# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("What are the top hackernews stories?", stream=True)
    asyncio.run(async_agent.aprint_response("What are the top hackernews stories?"))
