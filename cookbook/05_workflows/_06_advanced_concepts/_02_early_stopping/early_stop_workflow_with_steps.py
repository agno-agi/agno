from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# Create agents
content_creator = Agent(
    name="Content Creator",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions="Create engaging content on the given topic. Research and write comprehensive articles.",
)

fact_checker = Agent(
    name="Fact Checker",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Verify facts and check accuracy of content. Flag any misinformation.",
)

editor = Agent(
    name="Editor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Edit and polish content for publication. Ensure clarity and flow.",
)

publisher = Agent(
    name="Publisher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Prepare content for publication and handle final formatting.",
)


# Custom content quality check function
def content_quality_gate(step_input: StepInput) -> StepOutput:
    """Quality gate that checks content and may stop the workflow"""
    content = step_input.previous_step_content or ""

    # Simulate quality check - stop if content is too short or mentions certain topics
    if len(content) < 100:
        return StepOutput(
            step_name="content_quality_gate",
            content="❌ QUALITY CHECK FAILED: Content too short. Stopping workflow.",
            stop=True,  # ✅ Early termination
        )

    # Check for problematic content
    problematic_keywords = ["fake", "misinformation", "unverified", "conspiracy"]
    if any(keyword in content.lower() for keyword in problematic_keywords):
        return StepOutput(
            step_name="content_quality_gate",
            content="❌ QUALITY CHECK FAILED: Problematic content detected. Stopping workflow.",
            stop=True,  # ✅ Early termination
        )

    return StepOutput(
        step_name="content_quality_gate",
        content="✅ QUALITY CHECK PASSED: Content meets quality standards.",
        stop=False,  # Continue workflow
    )


# Create Steps sequence with early termination
content_pipeline = Steps(
    name="content_pipeline",
    description="Content creation pipeline with quality gates",
    steps=[
        Step(name="create_content", agent=content_creator),
        Step(
            name="quality_gate", executor=content_quality_gate
        ),  # ✅ Can stop workflow
        Step(name="fact_check", agent=fact_checker),  # ✅ Won't execute if stopped
        Step(name="edit_content", agent=editor),  # ✅ Won't execute if stopped
        Step(name="publish", agent=publisher),  # ✅ Won't execute if stopped
    ],
)

# Create workflow
if __name__ == "__main__":
    workflow = Workflow(
        name="Content Creation with Quality Gate",
        description="Content creation workflow with early termination on quality issues",
        steps=[
            content_pipeline,
            Step(
                name="final_review", agent=editor
            ),  # ✅ Won't execute if pipeline stopped
        ],
    )

    print("\n=== Test 2: Short content (should stop early) ===")
    workflow.print_response(
        input="Write a short note about conspiracy theories",
        markdown=True,
        stream=True,
    )
