from typing import List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field


class DifferentModel(BaseModel):
    name: str


class ResearchTopic(BaseModel):
    """Structured research topic with specific requirements"""

    topic: str
    focus_areas: List[str] = Field(description="Specific areas to focus on")
    target_audience: str = Field(description="Who this research is for")
    sources_required: int = Field(description="Number of sources needed", default=5)


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
if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation from blog posts to social media",
        db=SqliteDb(
            session_table="workflow_session",
            db_file="tmp/workflow.db",
        ),
        steps=[research_step, content_planning_step],
        input_schema=ResearchTopic,
    )

    print("=== Example: Research with Structured Topic ===")
    research_topic = ResearchTopic(
        topic="AI trends in 2024",
        focus_areas=[
            "Machine Learning",
            "Natural Language Processing",
            "Computer Vision",
            "AI Ethics",
        ],
        target_audience="Tech professionals and business leaders",
    )

    # 1. Should work properly, as its in sync with input schema
    content_creation_workflow.print_response(
        input=research_topic,
        markdown=True,
    )

    # 2. Should fail, as some fields present in input schema are missing here
    # content_creation_workflow.print_response(
    #     input=ResearchTopic(
    #         topic="AI trends in 2024",
    #         focus_areas=[
    #             "Machine Learning",
    #             "Natural Language Processing",
    #             "Computer Vision",
    #             "AI Ethics",
    #         ],
    #     ),
    #     markdown=True,
    # )

    # 3. Should fail, as its not in sync with input schema, diff pydantic model provided
    # content_creation_workflow.print_response(
    #     input=DifferentModel(name="test"),
    #     markdown=True,
    # )

    # 4. Pass a valid dict that matches ResearchTopic
    # content_creation_workflow.print_response(
    #     input={
    #         "topic": "AI trends in 2024",
    #         "focus_areas": ["Machine Learning", "Computer Vision"],
    #         "target_audience": "Tech professionals",
    #         "sources_required": 8
    #     },
    #     markdown=True,
    # )
