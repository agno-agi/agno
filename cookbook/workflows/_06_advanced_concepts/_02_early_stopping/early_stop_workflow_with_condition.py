from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow import Step, Workflow
from agno.workflow.condition import Condition
from agno.workflow.types import StepInput, StepOutput

# Create agents
researcher = Agent(
    name="Researcher",
    instructions="Research the given topic thoroughly and provide detailed findings.",
    tools=[DuckDuckGoTools()],
)

writer = Agent(
    name="Writer",
    instructions="Create engaging content based on research findings.",
)

reviewer = Agent(
    name="Reviewer",
    instructions="Review and improve the written content.",
)


# Custom compliance checker function
def compliance_checker(step_input: StepInput) -> StepOutput:
    """Compliance checker that can stop the condition if violations are found"""
    content = step_input.previous_step_content or ""

    # Simulate detecting compliance violations
    if "violation" in content.lower() or "illegal" in content.lower():
        return StepOutput(
            step_name="Compliance Checker",
            content="🚨 COMPLIANCE VIOLATION DETECTED! Content contains material that violates company policies. Stopping content creation workflow immediately.",
            stop=True,  # ✅ Request early termination from condition
        )
    else:
        return StepOutput(
            step_name="Compliance Checker",
            content="✅ Compliance check passed. Content meets all company policy requirements.",
            stop=False,
        )


# Custom quality assurance function
def quality_assurance(step_input: StepInput) -> StepOutput:
    """Quality assurance that runs after compliance check"""
    _ = step_input.previous_step_content or ""

    return StepOutput(
        step_name="Quality Assurance",
        content="✅ Quality assurance completed. Content meets quality standards and is ready for publication.",
        stop=False,
    )


# Condition evaluator function
def should_run_compliance_check(step_input: StepInput) -> bool:
    """Evaluate if compliance check should run based on content type"""
    content = step_input.input or ""

    # Run compliance check for sensitive topics
    sensitive_keywords = ["legal", "financial", "medical", "violation", "illegal"]
    return any(keyword in content.lower() for keyword in sensitive_keywords)


# Create workflow steps
research_step = Step(name="Research Content", agent=researcher)
compliance_check_step = Step(
    name="Compliance Check", executor=compliance_checker
)  # ✅ Can stop workflow
quality_assurance_step = Step(name="Quality Assurance", executor=quality_assurance)
write_step = Step(name="Write Article", agent=writer)
review_step = Step(name="Review Article", agent=reviewer)

# Create workflow with conditional compliance checks
workflow = Workflow(
    name="Content Creation with Conditional Compliance",
    description="Creates content with conditional compliance checks that can stop the workflow",
    steps=[
        research_step,  # Always runs first
        Condition(
            name="Compliance and QA Gate",
            evaluator=should_run_compliance_check,  # Only runs for sensitive content
            steps=[
                compliance_check_step,  # Step 1: Compliance check (may stop here)
                quality_assurance_step,  # Step 2: QA (only if compliance passes)
            ],
        ),
        write_step,  # This should NOT execute if compliance check stops
        review_step,  # This should NOT execute if compliance check stops
    ],
)

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
