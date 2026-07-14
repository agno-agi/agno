"""
Early Stop Loop
===============

Demonstrates stopping a looped workflow early using a safety-check step.
"""

from typing import List

from agno.agent import Agent
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow import Loop, Step, Workflow
from agno.workflow.types import StepInput, StepOutput

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
research_agent = Agent(
    name="Research Agent",
    role="Research specialist",
    tools=[HackerNewsTools(), WebSearchTools()],
    instructions="You are a research specialist. Research the given topic thoroughly.",
    markdown=True,
)

content_agent = Agent(
    name="Content Agent",
    role="Content creator",
    instructions="You are a content creator. Create engaging content based on research.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Define Functions
# ---------------------------------------------------------------------------
def safety_checker(step_input: StepInput) -> StepOutput:
    content = step_input.previous_step_content or ""

    if "AI" in content or "machine learning" in content:
        return StepOutput(
            step_name="Safety Checker",
            content="[ALERT] SAFETY CONCERN DETECTED! Content contains sensitive AI-related information. Stopping research loop for review.",
            stop=True,
        )
    return StepOutput(
        step_name="Safety Checker",
        content="[OK] Safety check passed. Content is safe to continue.",
        stop=False,
    )


def research_evaluator(outputs: List[StepOutput]) -> bool:
    if not outputs:
        print("[INFO] No research outputs - continuing loop")
        return False

    for output in outputs:
        if output.content and len(output.content) > 200:
            print(
                f"[PASS] Research evaluation passed - found substantial content ({len(output.content)} chars)"
            )
            return True

    print("[FAIL] Research evaluation failed - need more substantial research")
    return False


# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_hackernews_step = Step(
    name="Research HackerNews",
    agent=research_agent,
    description="Research trending topics on HackerNews",
)

safety_check_step = Step(
    name="Safety Check",
    executor=safety_checker,
    description="Check if research content is safe to continue",
)

research_web_step = Step(
    name="Research Web",
    agent=research_agent,
    description="Research additional information from web sources",
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Research with Safety Check Workflow",
    description="Research topics in loop with safety checks, stop if safety issues found",
    steps=[
        Loop(
            name="Research Loop with Safety",
            steps=[
                research_hackernews_step,
                safety_check_step,
                research_web_step,
            ],
            end_condition=research_evaluator,
            max_iterations=3,
        ),
        content_agent,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Testing Loop Early Termination with Safety Check ===")
    print("Expected: Safety check should detect 'AI' and stop the entire workflow")
    print()

    workflow.print_response(
        input="Research the latest trends in AI and machine learning, then create a summary",
        stream=True,
    )
