from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import Step, Workflow
from agno.workflow.parallel import Parallel
from agno.workflow.types import StepInput, StepOutput

# Create agents
researcher = Agent(name="Researcher", tools=[HackerNewsTools(), DuckDuckGoTools()])
writer = Agent(name="Writer")
reviewer = Agent(name="Reviewer")


# Custom safety checker function that can stop the entire workflow
def content_safety_checker(step_input: StepInput) -> StepOutput:
    """Safety checker that runs in parallel and can stop the workflow"""
    content = step_input.input or ""

    # Simulate detecting unsafe content that requires immediate stopping
    if "unsafe" in content.lower() or "dangerous" in content.lower():
        return StepOutput(
            step_name="Safety Checker",
            content="🚨 UNSAFE CONTENT DETECTED! Content contains dangerous material. Stopping entire workflow immediately for safety review.",
            stop=True,  # ✅ Request early termination from parallel execution
        )
    else:
        return StepOutput(
            step_name="Safety Checker",
            content="✅ Content safety verification passed. Material is safe to proceed.",
            stop=False,
        )


# Custom quality checker function
def quality_checker(step_input: StepInput) -> StepOutput:
    """Quality checker that runs in parallel"""
    content = step_input.input or ""

    # Simulate quality check
    if len(content) < 10:
        return StepOutput(
            step_name="Quality Checker",
            content="⚠️ Quality check failed: Content too short for processing.",
            stop=False,
        )
    else:
        return StepOutput(
            step_name="Quality Checker",
            content="✅ Quality check passed. Content meets processing standards.",
            stop=False,
        )


# Create individual steps
research_hn_step = Step(name="Research HackerNews", agent=researcher)
research_web_step = Step(name="Research Web", agent=researcher)
safety_check_step = Step(
    name="Safety Check", executor=content_safety_checker
)  # ✅ Can stop workflow
quality_check_step = Step(name="Quality Check", executor=quality_checker)
write_step = Step(name="Write Article", agent=writer)
review_step = Step(name="Review Article", agent=reviewer)

# Create workflow with parallel safety/quality checks
workflow = Workflow(
    name="Content Creation with Parallel Safety Checks",
    description="Creates content with parallel safety and quality checks that can stop the workflow",
    steps=[
        Parallel(
            research_hn_step,  # Research task 1
            research_web_step,  # Research task 2
            safety_check_step,  # Safety check (may stop here)
            quality_check_step,  # Quality check
            name="Research and Validation Phase",
        ),
        write_step,  # This should NOT execute if safety check stops
        review_step,  # This should NOT execute if safety check stops
    ],
)

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
