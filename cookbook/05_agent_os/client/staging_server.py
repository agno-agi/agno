"""AgentOS server for testing SSE reconnection with os-stg.agno.com"""

import json

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team
from agno.team.mode import TeamMode
from agno.tools import tool
from agno.tools.calculator import CalculatorTools
from agno.tools.reasoning import ReasoningTools


@tool(requires_confirmation=True)
def get_top_hackernews_stories(num_stories: int) -> str:
    """Fetch top stories from Hacker News.

    Args:
        num_stories: Number of stories to retrieve

    Returns:
        JSON string of story details
    """
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()
    all_stories = []
    for story_id in story_ids[:num_stories]:
        story_response = httpx.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        story = story_response.json()
        story.pop("text", None)
        all_stories.append(story)
    return json.dumps(all_stories)

db = SqliteDb(db_file="tmp/staging_test.db")

discord_bot = Agent(
    id="discord-bot",
    name="Discord Bot",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    instructions=[
        "You are a helpful AI assistant called Discord Bot.",
        "When asked to write something long, write at least 500 words with detailed explanations.",
    ],
    tools=[CalculatorTools()],
    markdown=True,
)

reasoning_agent = Agent(
    id="reasoning-agent",
    name="Reasoning Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    tools=[ReasoningTools(add_instructions=True), CalculatorTools()],
    instructions=[
        "You are an analytical agent that uses step-by-step reasoning.",
        "Always use your reasoning tools to think through complex problems.",
        "Use calculator tools for any math.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

researcher = Agent(
    id="researcher",
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["You research topics and provide detailed factual information."],
)

writer = Agent(
    id="writer",
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["You take research and write polished, engaging content."],
)

content_team = Team(
    id="content-team",
    name="Content Team",
    mode=TeamMode.coordinate,
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, writer],
    db=db,
    instructions=["Coordinate the researcher and writer to produce well-researched content."],
    markdown=True,
    show_members_responses=True,
)

hitl_agent = Agent(
    id="hitl-agent",
    name="HITL Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    instructions=[
        "You are a helpful assistant with access to Hacker News.",
        "When asked about tech news, use the get_top_hackernews_stories tool.",
    ],
    tools=[get_top_hackernews_stories],
    markdown=True,
)

agent_os = AgentOS(
    id="sse-reconnect-staging",
    agents=[discord_bot, hitl_agent, reasoning_agent],
    teams=[content_team],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="staging_server:app", reload=True)
