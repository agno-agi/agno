"""
Early Stop Parallel
===================

Demonstrates stopping the workflow from within a step running inside a `Parallel` block.
"""

from agno.agent import Agent
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow import Step, Workflow
from agno.workflow.parallel import Parallel
from agno.workflow.types import StepInput, StepOutput

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
researcher = Agent(name="Researcher", tools=[HackerNewsTools(), WebSearchTools()])
writer = Agent(name="Writer")
reviewer = Agent(name="Reviewer")


# ---------------------------------------------------------------------------
# Define Functions
# ---------------------------------------------------------------------------
def content_safety_checker(step_input: StepInput) -> StepOutput:
    content = step_input.input or ""

    if "unsafe" in content.lower() or "dangerous" in content.lower():
        return StepOutput(
            step_name="Safety Checker",
            content="[ALERT] UNSAFE CONTENT DETECTED! Content contains dangerous material. Stopping entire workflow immediately for safety review.",
            stop=True,
        )
    return StepOutput(
        step_name="Safety Checker",
        content="[PASS] Content safety verification passed. Material is safe to proceed.",
        stop=False,
    )


def quality_checker(step_input: StepInput) -> StepOutput:
    content = step_input.input or ""

    if len(content) < 10:
        return StepOutput(
            step_name="Quality Checker",
            content="[WARN] Quality check failed: Content too short for processing.",
            stop=False,
        )
    return StepOutput(
        step_name="Quality Checker",
        content="[PASS] Quality check passed. Content meets processing standards.",
        stop=False,
    )


# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_hn_step = Step(name="Research HackerNews", agent=researcher)
research_web_step = Step(name="Research Web", agent=researcher)
safety_check_step = Step(name="Safety Check", executor=content_safety_checker)
quality_check_step = Step(name="Quality Check", executor=quality_checker)
write_step = Step(name="Write Article", agent=writer)
review_step = Step(name="Review Article", agent=reviewer)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Content Creation with Parallel Safety Checks",
    description="Creates content with parallel safety and quality checks that can stop the workflow",
    steps=[
        Parallel(
            research_hn_step,
            research_web_step,
            safety_check_step,
            quality_check_step,
            name="Research and Validation Phase",
        ),
        write_step,
        review_step,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Testing Parallel Early Termination with Safety Check ===")
    print("Expected: Safety check should detect 'unsafe' and stop the entire workflow")
    print(
        "Note: All parallel steps run concurrently, but safety check will stop the workflow"
    )
    print()

    workflow.print_response(
        input="Write about unsafe and dangerous AI developments that could harm society",
    )
