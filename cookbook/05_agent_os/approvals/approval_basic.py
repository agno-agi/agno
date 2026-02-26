"""
Approval Basic
=============================

Approval-backed HITL: @approval + @tool(requires_confirmation=True) with persistent DB record.
"""

import json
import httpx

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from agno.os import AgentOS
DB_FILE = "tmp/approvals_test.db"


@approval(type="required")
@tool(requires_confirmation=True)
def get_top_hackernews_stories(num_stories: int) -> str:
    """Fetch top stories from Hacker News.

    Args:
        num_stories (int): Number of stories to retrieve.

    Returns:
        str: JSON string of story details.
    """
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()
    stories = []
    for story_id in story_ids[:num_stories]:
        story = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        ).json()
        story.pop("text", None)
        stories.append(story)
    return json.dumps(stories)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_top_hackernews_stories],
    markdown=True,
    db=db,
)


agent_os = AgentOS(
    description="Example app for tracing with multiple models, agents, teams, and workflows",
    agents=[
        agent,
        ],
        tracing=True,
        db=db,
        
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="approval_basic:app", reload=True)