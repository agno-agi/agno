from typing import List

from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import Loop, Step, Workflow
from agno.workflow.types import StepInput, StepOutput

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


# Custom function that will trigger early termination
def safety_checker(step_input: StepInput) -> StepOutput:
    """Safety checker that stops the loop if certain keywords are detected"""
    content = step_input.previous_step_content or ""

    # Simulate finding problematic content that requires stopping
    if (
        "AI" in content or "machine learning" in content
    ):  # Will trigger on our test message
        return StepOutput(
            step_name="Safety Checker",
            content="🚨 SAFETY CONCERN DETECTED! Content contains sensitive AI-related information. Stopping research loop for review.",
            stop=True,  # ✅ Request early termination
        )
    else:
        return StepOutput(
            step_name="Safety Checker",
            content="✅ Safety check passed. Content is safe to continue.",
            stop=False,
        )


# Create research steps
research_hackernews_step = Step(
    name="Research HackerNews",
    agent=research_agent,
    description="Research trending topics on HackerNews",
)

safety_check_step = Step(
    name="Safety Check",
    executor=safety_checker,  # ✅ Custom function that can stop the loop
    description="Check if research content is safe to continue",
)

research_web_step = Step(
    name="Research Web",
    agent=research_agent,
    description="Research additional information from web sources",
)


# Normal end condition (keeps the original logic) + early termination check
def research_evaluator(outputs: List[StepOutput]) -> bool:
    """
    Evaluate if research results are sufficient or if early termination was requested
    Returns True to break the loop, False to continue
    """
    if not outputs:
        print("❌ No research outputs - continuing loop")
        return False

    # Original logic: Check if any output contains substantial content
    for output in outputs:
        if output.content and len(output.content) > 200:
            print(
                f"✅ Research evaluation passed - found substantial content ({len(output.content)} chars)"
            )
            return True

    print("❌ Research evaluation failed - need more substantial research")
    return False


# Create workflow with loop that includes safety checker
workflow = Workflow(
    name="Research with Safety Check Workflow",
    description="Research topics in loop with safety checks, stop if safety issues found",
    steps=[
        Loop(
            name="Research Loop with Safety",
            steps=[
                research_hackernews_step,  # Step 1: Research
                safety_check_step,  # Step 2: Safety check (may stop here)
                research_web_step,  # Step 3: More research (only if safety passes)
            ],
            end_condition=research_evaluator,
            max_iterations=3,
        ),
        content_agent,  # This should NOT execute if safety check stops the loop
    ],
)

if __name__ == "__main__":
    print("=== Testing Loop Early Termination with Safety Check ===")
    print("Expected: Safety check should detect 'AI' and stop the entire workflow")
    print()

    workflow.print_response(
        input="Research the latest trends in AI and machine learning, then create a summary",
        stream=True,
    )
