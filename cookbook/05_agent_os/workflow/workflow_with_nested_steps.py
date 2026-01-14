from typing import List

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb

# Import the workflows
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.loop import Loop
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# Define the research agents
hackernews_agent = Agent(
    name="HackerNews Researcher",
    instructions="You are a researcher specializing in finding the latest tech news and discussions from Hacker News. Focus on startup trends, programming topics, and tech industry insights.",
    tools=[HackerNewsTools()],
)

web_agent = Agent(
    name="Web Researcher",
    instructions="You are a comprehensive web researcher. Search across multiple sources including news sites, blogs, and official documentation to gather detailed information.",
    tools=[DuckDuckGoTools()],
)

content_agent = Agent(
    name="Content Publisher",
    instructions="You are a content creator who takes research data and creates engaging, well-structured articles. Format the content with proper headings, bullet points, and clear conclusions.",
)

# Create the research steps
research_hackernews = Step(
    name="research_hackernews",
    agent=hackernews_agent,
    description="Research latest tech trends from Hacker News",
)

research_web = Step(
    name="research_web",
    agent=web_agent,
    description="Comprehensive web research on the topic",
)

publish_content = Step(
    name="publish_content",
    agent=content_agent,
    description="Create and format final content for publication",
)

# End condition function for the loop


def research_quality_check(outputs: List[StepOutput]) -> bool:
    """
    Evaluate if research results are sufficient
    Returns True to break the loop, False to continue
    """
    if not outputs:
        return False

    # Check if any output contains substantial content
    for output in outputs:
        if output.content and len(output.content) > 300:
            print(
                f"✅ Research quality check passed - found substantial content ({len(output.content)} chars)"
            )
            return True

    print("❌ Research quality check failed - need more substantial research")
    return False


# Create a Loop step for deep tech research
deep_tech_research_loop = Loop(
    name="Deep Tech Research Loop",
    steps=[research_hackernews],
    end_condition=research_quality_check,
    max_iterations=3,
    description="Perform iterative deep research on tech topics",
)

# Router function that selects between simple web research or deep tech research loop


def research_strategy_router(step_input: StepInput) -> List[Step]:
    """
    Decide between simple web research or deep tech research loop based on the input topic.
    Returns either a single web research step or a tech research loop.
    """
    return [deep_tech_research_loop]


workflow = Workflow(
    name="Adaptive Research Workflow",
    description="Intelligently selects between simple web research or deep iterative tech research based on topic complexity",
    steps=[
        Router(
            name="research_strategy_router",
            selector=research_strategy_router,
            choices=[research_web, deep_tech_research_loop],
            description="Chooses between simple web research or deep tech research loop",
        ),
        publish_content,
    ],
    db=PostgresDb(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
)

# Initialize the AgentOS with the workflows
agent_os = AgentOS(
    description="Example OS setup",
    workflows=[workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="workflow_with_nested_steps:app", reload=True)
