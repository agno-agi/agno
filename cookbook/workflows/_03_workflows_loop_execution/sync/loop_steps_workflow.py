from typing import List

from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import Loop, Step, Workflow
from agno.workflow.types import StepOutput

# Create agents for research
research_agent = Agent(
    name="Research Agent",
    role="Research specialist",
    tools=[HackerNewsTools(), DuckDuckGoTools()],
    instructions="You are a research specialist. Research the given topic thoroughly.",
    markdown=True,
)

content_agent = Agent(
    name="Content Agent",
    role="Content creator",
    instructions="You are a content creator. Create engaging content based on research.",
    markdown=True,
)

# Create research steps
research_hackernews_step = Step(
    name="Research HackerNews",
    agent=research_agent,
    description="Research trending topics on HackerNews",
)

research_web_step = Step(
    name="Research Web",
    agent=research_agent,
    description="Research additional information from web sources",
)

content_step = Step(
    name="Create Content",
    agent=content_agent,
    description="Create content based on research findings",
)


# End condition function
def research_evaluator(outputs: List[StepOutput]) -> bool:
    """
    Evaluate if research results are sufficient
    Returns True to break the loop, False to continue
    """
    # Check if any outputs are present
    if not outputs:
        return False

    # Check if any output contains substantial content
    for output in outputs:
        if output.content and len(output.content) > 200:
            print(
                f"✅ Research evaluation passed - found substantial content ({len(output.content)} chars)"
            )
            return True

    print("❌ Research evaluation failed - need more substantial research")
    return False


# Create workflow with loop
workflow = Workflow(
    name="Research and Content Workflow",
    description="Research topics in a loop until conditions are met, then create content",
    steps=[
        Loop(
            name="Research Loop",
            steps=[research_hackernews_step, research_web_step],
            end_condition=research_evaluator,
            max_iterations=3,  # Maximum 3 iterations
        ),
        content_step,
    ],
)

if __name__ == "__main__":
    # Test the workflow
    workflow.print_response(
        input="Research the latest trends in AI and machine learning, then create a summary",
    )
