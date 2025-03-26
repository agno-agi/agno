import asyncio
import json
from typing import AsyncIterator

import httpx
from agno.agent import Agent
from agno.tools import FunctionCall, tool


async def pre_hook(fc: FunctionCall):
    print(f"About to run: {fc.function.name}")


async def post_hook(fc: FunctionCall):
    print("After running: ", fc.function.name)


@tool(show_result=True, pre_hook=pre_hook, post_hook=post_hook)
async def get_top_hackernews_stories(agent: Agent) -> AsyncIterator[str]:
    num_stories = agent.context.get("num_stories", 5) if agent.context else 5

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


agent = Agent(
    context={
        "num_stories": 2,
    },
    tools=[get_top_hackernews_stories],
    markdown=True,
    show_tool_calls=True,
)
if __name__ == "__main__":
    asyncio.run(agent.aprint_response("What are the top hackernews stories?"))
