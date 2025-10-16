from typing import List

from agno.agent.agent import Agent
from agno.models.anthropic import Claude
from agno.team.team import Team
from agno.tools.firecrawl import FirecrawlTools
from agno.tools.wikipedia import WikipediaTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from db import db
from pydantic import BaseModel, Field


# ************* Input Schema *************
class ResearchTopic(BaseModel):
    """Structured research topic with specific requirements"""

    topic: str
    focus_areas: List[str] = Field(description="Specific areas to focus on")


# *******************************


# ************* Agents *************
wikipedia_agent = Agent(
    name="Wikipedia Agent",
    model=Claude(id="claude-sonnet-4-0"),
    role="Extract key insights and content from Wikipedia articles",
    tools=[WikipediaTools()],
)
search_agent = Agent(
    name="Search Agent",
    model=Claude(id="claude-sonnet-4-0"),
    role="Search the web for the latest news and trends using Firecrawl",
    tools=[FirecrawlTools()],
)
writer_agent = Agent(
    name="Writer Agent",
    model=Claude(id="claude-sonnet-4-0"),
    instructions=[
        "Write a detailed report on the provided topic and research content",
    ],
)
# *******************************


# ************* Team *************
research_team = Team(
    name="Research Team",
    model=Claude(id="claude-sonnet-4-5"),
    members=[wikipedia_agent, search_agent],
    instructions="Research tech topics from Wikipedia and the web",
)
# *******************************


# ************* Workflow Steps *************
research_step = Step(
    name="Research Step",
    team=research_team,
)

writer_step = Step(
    name="Writer Step",
    agent=writer_agent,
)
# *******************************


# ************* Workflow *************
research_workflow = Workflow(
    name="Research Workflow",
    description="Automated research on a topic",
    db=db,
    steps=[research_step, writer_step],
    input_schema=ResearchTopic,
)
# *******************************
