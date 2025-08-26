"""
1. Run: `pip install openai ddgs newspaper4k lxml_html_clean agno` to install the dependencies
2. Run: `python cookbook/storage/mongodb_storage/mongodb_storage_for_team.py` to run the agent
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.mysql import MySQLStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel

# MySQL connection settings
db_url = "mysql+pymysql://ai:ai@localhost:3306/ai"


class Article(BaseModel):
    title: str
    summary: str
    reference_links: List[str]


hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIChat("gpt-4o"),
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a topic",
    tools=[DuckDuckGoTools()],
    add_datetime_to_instructions=True,
)


hn_team = Team(
    name="HackerNews Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    members=[hn_researcher, web_searcher],
    storage=MySQLStorage(
        table_name="team_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
    instructions=[
        "First, search hackernews for what the user is asking about.",
        "Then, ask the web searcher to search for each story to get more information.",
        "Finally, provide a thoughtful and engaging summary.",
    ],
    response_model=Article,
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
    add_member_tools_to_system_message=False,
)

hn_team.print_response("Write an article about the top 2 stories on hackernews")


print(
    f"Session IDs created in DB: {hn_team.storage.get_all_session_ids(entity_id=hn_team.team_id)}"
)
