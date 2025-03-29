import json
from typing import Iterator

import httpx
from agno.agent import Agent
from agno.tools import tool


@tool(show_result=True)
def get_top_hackernews_stories(agent: Agent) -> Iterator[str]:
    num_stories = agent.context.get("num_stories", 5) if agent.context else 5

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
    context={
        "num_stories": 2,
    },
    tools=[get_top_hackernews_stories],
    markdown=True,
    show_tool_calls=True,
)
agent.print_response("What are the top hackernews stories?", stream=True)
