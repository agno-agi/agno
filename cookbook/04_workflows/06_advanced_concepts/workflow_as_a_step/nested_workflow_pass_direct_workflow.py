"""
Nested Workflow - Auto-Wrap (Passing Workflow Directly)

Demonstrates passing a Workflow directly in the steps list without
wrapping it in a Step(). The outer workflow auto-wraps it, using the
inner workflow's name as the step name.

Both approaches are equivalent:
    # Explicit (recommended for clarity)
    steps=[Step(name="research_phase", workflow=inner_workflow)]

    # Auto-wrap (concise shorthand)
    steps=[inner_workflow]
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def summarize(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Summary: {prev[:200]}")


# --- Inner workflow ---
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You are a research assistant. Be concise (2-3 sentences).",
)

inner_workflow = Workflow(
    name="Research Workflow",
    description="Researches a topic and summarizes",
    steps=[
        Step(name="research", agent=researcher),
        Step(name="summarize", executor=summarize),
    ],
)

# --- Outer workflow: pass inner_workflow directly (no Step wrapper) ---
writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Write a polished paragraph from the research provided.",
)

outer_workflow = Workflow(
    name="Auto-Wrap Example",
    description="Inner workflow passed directly in steps list",
    steps=[
        inner_workflow,  # Auto-wrapped into Step(name="Research Workflow", workflow=inner_workflow)
        Step(name="write", agent=writer),
    ],
)


if __name__ == "__main__":
    outer_workflow.print_response(
        input="What are the benefits of open source software?",
        stream=True,
    )
