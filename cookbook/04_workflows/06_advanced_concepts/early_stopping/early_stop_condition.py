"""
Early Stop Condition
====================

Demonstrates stopping an entire workflow from inside a `Condition` branch.
"""

from agno.agent import Agent
from agno.tools.websearch import WebSearchTools
from agno.workflow import Step, Workflow
from agno.workflow.condition import Condition
from agno.workflow.types import StepInput, StepOutput

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    instructions="Research the given topic thoroughly and provide detailed findings.",
    tools=[WebSearchTools()],
)

writer = Agent(
    name="Writer",
    instructions="Create engaging content based on research findings.",
)

reviewer = Agent(
    name="Reviewer",
    instructions="Review and improve the written content.",
)


# ---------------------------------------------------------------------------
# Define Functions
# ---------------------------------------------------------------------------
def compliance_checker(step_input: StepInput) -> StepOutput:
    content = step_input.previous_step_content or ""

    if "violation" in content.lower() or "illegal" in content.lower():
        return StepOutput(
            step_name="Compliance Checker",
            content="[ALERT] COMPLIANCE VIOLATION DETECTED! Content contains material that violates company policies. Stopping content creation workflow immediately.",
            stop=True,
        )
    return StepOutput(
        step_name="Compliance Checker",
        content="[PASS] Compliance check passed. Content meets all company policy requirements.",
        stop=False,
    )


def quality_assurance(step_input: StepInput) -> StepOutput:
    _ = step_input.previous_step_content or ""

    return StepOutput(
        step_name="Quality Assurance",
        content="[PASS] Quality assurance completed. Content meets quality standards and is ready for publication.",
        stop=False,
    )


def should_run_compliance_check(step_input: StepInput) -> bool:
    content = step_input.input or ""
    sensitive_keywords = ["legal", "financial", "medical", "violation", "illegal"]
    return any(keyword in content.lower() for keyword in sensitive_keywords)


# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(name="Research Content", agent=researcher)
compliance_check_step = Step(name="Compliance Check", executor=compliance_checker)
quality_assurance_step = Step(name="Quality Assurance", executor=quality_assurance)
write_step = Step(name="Write Article", agent=writer)
review_step = Step(name="Review Article", agent=reviewer)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Content Creation with Conditional Compliance",
    description="Creates content with conditional compliance checks that can stop the workflow",
    steps=[
        research_step,
        Condition(
            name="Compliance and QA Gate",
            evaluator=should_run_compliance_check,
            steps=[
                compliance_check_step,
                quality_assurance_step,
            ],
        ),
        write_step,
        review_step,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Testing Condition Early Termination with Compliance Check ===")
    print(
        "Expected: Compliance check should detect 'violation' and stop the entire workflow"
    )
    print(
        "Note: Condition will evaluate to True (sensitive content), then compliance check will stop"
    )
    print()

    workflow.print_response(
        input="Research legal violation cases and create content about illegal financial practices",
        stream=True,
    )
