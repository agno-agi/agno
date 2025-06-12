import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.googlesearch import GoogleSearchTools
from agno.workflow.v2.task import Task
from agno.workflow.v2.workflow import Workflow

# Define agents
blog_analyzer = Agent(
    name="Blog Analyzer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleSearchTools()],
    instructions="Extract key insights and content from blog posts",
)

content_planner = Agent(
    name="Content Planner",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Create engaging social media content plans based on analysis",
)

# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    mode="coordinate",
    members=[blog_analyzer, content_planner],
    instructions="Analyze content and create comprehensive social media strategy",
)

# Define tasks with consistent query-based input
analyze_blog_task = Task(
    name="analyze_blog",
    agent=blog_analyzer,
    description="Analyze the provided topic and extract key insights",
)

plan_content_task = Task(
    name="plan_content",
    agent=content_planner,
    description="Create social media content plan based on the research topic and previous analysis",
)

research_task = Task(
    name="research_content",
    team=research_team,
    description="Deep research and analysis of content",
)

# Create and use workflow


async def main():
    content_creation_workflow = Workflow(
        name="Content Creation Workflow",
        description="Automated content creation from blog posts to social media",
        storage=SqliteStorage(
            table_name="workflow_v2",
            db_file="tmp/workflow_v2.db",
            mode="workflow_v2",
        ),
        tasks=[research_task, plan_content_task],
    )
    print("=== Research Pipeline (Rich Display) ===")
    try:
        await content_creation_workflow.aprint_response(
            query="AI trends in 2024",
            markdown=True,
            show_time=True,
            show_task_details=True,
        )
    except Exception as e:
        print(f"Research sequence failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
