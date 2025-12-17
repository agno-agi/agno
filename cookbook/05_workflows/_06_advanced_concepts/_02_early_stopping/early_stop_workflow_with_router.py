from typing import List

from agno.agent.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
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


# Custom safety checker function
def content_safety_checker(step_input: StepInput) -> StepOutput:
    """Safety checker that can stop the router if inappropriate content is detected"""
    content = step_input.previous_step_content or ""

    # Simulate detecting inappropriate content that requires stopping
    if "controversial" in content.lower() or "sensitive" in content.lower():
        return StepOutput(
            step_name="Content Safety Checker",
            content="🚨 CONTENT SAFETY VIOLATION! Research contains controversial or sensitive material. Stopping workflow for manual review.",
            stop=True,  # ✅ Request early termination
        )
    else:
        return StepOutput(
            step_name="Content Safety Checker",
            content="✅ Content safety check passed. Material is appropriate for publication.",
            stop=False,
        )


# Create the research steps
research_hackernews = Step(
    name="research_hackernews",
    agent=hackernews_agent,
    description="Research latest tech trends from Hacker News",
)

safety_check = Step(
    name="safety_check",
    executor=content_safety_checker,  # ✅ Custom function that can stop the router
    description="Check if research content is safe for publication",
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


# Router function that returns multiple steps including safety check
def research_router(step_input: StepInput) -> List[Step]:
    """
    Decide which research method to use based on the input topic.
    Returns a list containing the step(s) to execute including safety check.
    """
    topic = step_input.previous_step_content or step_input.input or ""
    topic = topic.lower()

    # Check if the topic is tech/startup related - use HackerNews
    tech_keywords = [
        "startup",
        "programming",
        "ai",
        "machine learning",
        "software",
        "developer",
        "coding",
        "tech",
        "silicon valley",
        "venture capital",
        "cryptocurrency",
        "blockchain",
        "open source",
        "github",
    ]

    if any(keyword in topic for keyword in tech_keywords):
        print(f"🔍 Tech topic detected: Using HackerNews research for '{topic}'")
        return [
            research_hackernews,  # Step 1: Research
            safety_check,  # Step 2: Safety check (may stop here)
            research_web,  # Step 3: Additional research (only if safety passes)
        ]
    else:
        print(f"🌐 General topic detected: Using web research for '{topic}'")
        return [
            research_web,  # Step 1: Research
            safety_check,  # Step 2: Safety check (may stop here)
        ]


workflow = Workflow(
    name="Research with Safety Router Workflow",
    description="Intelligently routes research methods with safety checks that can stop the workflow",
    steps=[
        Router(
            name="research_safety_router",
            selector=research_router,
            choices=[
                research_hackernews,
                safety_check,
                research_web,
            ],  # Available choices
            description="Intelligently selects research method with safety checks",
        ),
        publish_content,  # This should NOT execute if safety check stops the router
    ],
)

if __name__ == "__main__":
    print("=== Testing Router Early Termination with Safety Check ===")
    print(
        "Expected: Safety check should detect 'controversial' and stop the entire workflow"
    )
    print()

    workflow.print_response(
        input="Research the latest controversial trends in AI and machine learning",
        stream=True,
    )
