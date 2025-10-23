"""
Run: `pip install openai ddgs sqlalchemy aiosqlite` to install dependencies
Run: `python cookbook/db/async_sqlite/async_sqlite_for_workflow.py` to run the workflow
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Initialize AsyncSqliteDb with a database file
db = AsyncSqliteDb(db_file="workflow_storage.db")

hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
)
web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    role="Search the web for the latest news and trends",
)
content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)

research_team = Team(
    name="Research Team",
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)

research_step = Step(
    name="Research Step",
    team=research_team,
)
content_planning_step = Step(
    name="Content Planning Step",
    agent=content_planner,
)
content_creation_workflow = Workflow(
    name="Content Creation Workflow",
    description="Automated content creation from blog posts to social media",
    db=db,
    steps=[research_step, content_planning_step],
)

if __name__ == "__main__":
    asyncio.run(
        content_creation_workflow.aprint_response(
            input="AI trends in 2024",
            markdown=True,
        )
    )
