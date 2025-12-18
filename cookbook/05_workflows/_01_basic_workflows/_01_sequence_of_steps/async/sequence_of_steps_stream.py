"""
This example shows a basic sequential sequence of steps that run agents and teams.

This shows how to stream the response from the steps.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Define agents
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

# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)
content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Plan a content schedule over 4 weeks for the provided topic and research content",
        "Ensure that I have posts for 3 posts per week",
    ],
)

# Define steps
research_step = Step(
    name="Research Step",
    team=research_team,
)

content_planning_step = Step(
    name="Content Planning Step",
    agent=content_planner,
)


# Create and use workflow
async def main():
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation from blog posts to social media",
        db=SqliteDb(
            session_table="workflow_session",
            db_file="tmp/workflow.db",
        ),
        steps=[research_step, content_planning_step],
    )
    await content_creation_workflow.aprint_response(
        input="AI agent frameworks 2025",
        markdown=True,
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
