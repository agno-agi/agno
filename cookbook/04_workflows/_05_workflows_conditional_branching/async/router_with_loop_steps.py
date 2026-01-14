import asyncio
from typing import List

from agno.agent.agent import Agent
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
    # Use the original workflow message if this is the first step
    topic = step_input.previous_step_content or step_input.input or ""
    topic = topic.lower()

    # Check if the topic requires deep tech research
    deep_tech_keywords = [
        "startup trends",
        "ai developments",
        "machine learning research",
        "programming languages",
        "developer tools",
        "silicon valley",
        "venture capital",
        "cryptocurrency analysis",
        "blockchain technology",
        "open source projects",
        "github trends",
        "tech industry",
        "software engineering",
    ]

    # Check if it's a complex tech topic that needs deep research
    if any(keyword in topic for keyword in deep_tech_keywords) or (
        "tech" in topic and len(topic.split()) > 3
    ):
        print(
            f"🔬 Deep tech topic detected: Using iterative research loop for '{topic}'"
        )
        return [deep_tech_research_loop]
    else:
        print(f"🌐 Simple topic detected: Using basic web research for '{topic}'")
        return [research_web]


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
)

if __name__ == "__main__":
    print("=== Testing with deep tech topic ===")
    asyncio.run(
        workflow.aprint_response(
            "Latest developments in artificial intelligence and machine learning and deep tech research trends"
        )
    )
