import httpx
from agno.agent import Agent
from agno.tools import tool


@tool(
    name="fetch_hackernews_stories",
    description="Get top stories from Hacker News",
    show_result=True,
    instructions="When using the Hacker News API:\n1. Present stories in a clean, readable format\n2. Provide context when a URL is missing\n3. Be aware of rate limiting - results are cached for 1 hour",
    add_instructions=True,
    think=True,
)
def get_top_hackernews_stories(num_stories: int = 5) -> str:
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()

    # Get story details
    stories = []
    for story_id in story_ids[:num_stories]:
        story_response = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        )
        story = story_response.json()
        stories.append(f"{story.get('title')} - {story.get('url', 'No URL')}")

    return "\n".join(stories)


agent = Agent(
    tools=[get_top_hackernews_stories],
    markdown=True,
    show_tool_calls=True,
    debug_mode=True,
)

agent.print_response(
    "Show me the top news from Hacker News and summarize them", stream=True
)
