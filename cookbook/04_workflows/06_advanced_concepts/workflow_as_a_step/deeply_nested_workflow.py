"""
Deeply Nested Workflow (3 Levels)

Demonstrates composing workflows three levels deep:
  Level 1 (outermost): Orchestrates the full pipeline
  Level 2: Research workflow with parallel data gathering
  Level 3: Each parallel branch is itself a mini-workflow
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def merge_results(step_input: StepInput) -> StepOutput:
    """Merge content from previous steps."""
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Merged: {prev[:500]}")


# ==========================================================================
# Level 3: Mini-workflows for individual research tasks
# ==========================================================================

data_agent = Agent(
    name="Data Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Gather raw data and statistics on the topic. Be concise (2-3 sentences).",
)

analysis_agent = Agent(
    name="Analysis Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Analyze the data provided. Identify key trends. Be concise (2-3 sentences).",
)

# Level 3a: Data collection mini-workflow
data_workflow = Workflow(
    name="Data Collection",
    description="Collects and analyzes raw data",
    steps=[
        Step(name="gather", agent=data_agent),
        Step(name="analyze", agent=analysis_agent),
    ],
)

opinion_agent = Agent(
    name="Opinion Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Provide expert opinion and perspective on the topic. Be concise (2-3 sentences).",
)

# Level 3b: Expert opinion mini-workflow
opinion_workflow = Workflow(
    name="Expert Opinion",
    description="Gathers expert perspectives",
    steps=[
        Step(name="opinion", agent=opinion_agent),
    ],
)

# ==========================================================================
# Level 2: Research workflow that runs Level 3 workflows in parallel
# ==========================================================================

level2_workflow = Workflow(
    name="Comprehensive Research",
    description="Runs data collection and expert opinion in parallel",
    steps=[
        Parallel(
            Step(name="data_branch", workflow=data_workflow),
            Step(name="opinion_branch", workflow=opinion_workflow),
            name="parallel_research",
        ),
        Step(name="merge", executor=merge_results),
    ],
)

# ==========================================================================
# Level 1: Outermost workflow
# ==========================================================================

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Write a polished short paragraph synthesizing all research provided.",
)

outer_workflow = Workflow(
    name="Full Pipeline",
    description="3-level nested workflow: research (parallel mini-workflows) -> write",
    steps=[
        Step(name="research", workflow=level2_workflow),
        Step(name="write", agent=writer),
    ],
)


if __name__ == "__main__":
    print("Running 3-level nested workflow...")
    print("Level 1: Full Pipeline")
    print("  Level 2: Comprehensive Research (parallel)")
    print("    Level 3a: Data Collection (gather -> analyze)")
    print("    Level 3b: Expert Opinion")
    print("  Writer")
    print("=" * 50)

    outer_workflow.print_response(
        input="What is the future of renewable energy?",
        stream=True,
    )
