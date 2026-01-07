import httpx
from agno.agent import Agent
from agno.tools import tool


@tool(
    name="fetch_hackernews_stories",
    description="Get top stories from Hacker News",
    show_result=True,
    instructions="""
        Use this tool when:
          1. The user wants to see recent popular tech news or discussions
          2. You need examples of trending technology topics
          3. The user asks for Hacker News content or tech industry stories

        The tool will return titles and URLs for the specified number of top stories. When presenting results:
          - Highlight interesting or unusual stories
          - Summarize key themes if multiple stories are related
          - If summarizing, mention the original source is Hacker News
    """,
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
)

agent.print_response(
    "Show me the top news from Hacker News and summarize them", stream=True
)
