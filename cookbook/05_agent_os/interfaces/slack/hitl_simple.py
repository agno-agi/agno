"""
Slack HITL — Simple Confirmation
================================

Minimal example: agent with one tool that requires confirmation.
Use this to verify the HITL card appears in Slack.

Try in Slack:
  @bot get me the top 3 hacker news stories
"""

import json

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool


@tool(requires_confirmation=True)
def get_top_hackernews_stories(num_stories: int) -> str:
    """Fetch top stories from Hacker News.

    Args:
        num_stories: Number of stories to retrieve

    Returns:
        JSON string containing story details
    """
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()

    all_stories = []
    for story_id in story_ids[:num_stories]:
        story_response = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        )
        story = story_response.json()
        story.pop("text", None)
        all_stories.append(story)
    return json.dumps(all_stories)


db = SqliteDb(
    db_file="tmp/hitl_simple.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="HN Agent",
    id="hn-agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[get_top_hackernews_stories],
    markdown=True,
    db=db,
)

agent_os = AgentOS(
    description="Slack HITL — simple confirmation test",
    agents=[agent],
    db=db,
    interfaces=[
        Slack(
            agent=agent,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_simple:app", reload=True, port=7777)
