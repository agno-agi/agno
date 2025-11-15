"""Use Async MySQL as the database for a team.
Run `pip install openai duckduckgo-search newspaper4k lxml_html_clean agno sqlalchemy asyncmy` to install the dependencies
"""

import asyncio
import uuid
from typing import List

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.mysql import AsyncMySQLDb
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from pydantic import BaseModel

db_url = "mysql+asyncmy://ai:ai@localhost:3306/ai"
db = AsyncMySQLDb(db_url=db_url)


class Article(BaseModel):
    title: str
    summary: str
    reference_links: List[str]


hn_researcher = Agent(
    name="HackerNews Researcher",
    role="Gets top stories from hackernews.",
    tools=[HackerNewsTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    role="Searches the web for information on a topic",
    tools=[DuckDuckGoTools()],
    add_datetime_to_context=True,
)


hn_team = Team(
    name="HackerNews Team",
    members=[hn_researcher, web_searcher],
    db=db,
    instructions=[
        "First, search hackernews for what the user is asking about.",
        "Then, ask the web searcher to search for each story to get more information.",
        "Finally, provide a thoughtful and engaging summary.",
    ],
    output_schema=Article,
    markdown=True,
    show_members_responses=True,
)


async def main():
    """Run the agent queries in the same event loop"""
    session_id = str(uuid.uuid4())
    await hn_team.aprint_response(
        "Write an article about the top 2 stories on hackernews", session_id=session_id
    )
    session_data = await db.get_session(
        session_id=session_id, session_type=SessionType.TEAM
    )
    print("\n=== SESSION DATA ===")
    print(session_data.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
