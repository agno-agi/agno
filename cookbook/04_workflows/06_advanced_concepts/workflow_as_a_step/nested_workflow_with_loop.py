"""
Nested Workflow with Loop

Demonstrates using a workflow (containing a Loop step) as a step
in an outer workflow. The inner workflow iteratively refines research
until it meets a quality threshold, then the outer workflow writes.
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.workflow import Loop
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow


def is_detailed_enough(outputs: List[StepOutput]) -> bool:
    """End the loop when the output is sufficiently detailed (> 200 chars)."""
    if not outputs:
        return False
    last = outputs[-1]
    return last.content is not None and len(str(last.content)) > 200


# --- Inner workflow: iterative research ---
researcher = Agent(
    name="Iterative Researcher",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=(
        "You are a researcher. Each iteration, expand on the previous research "
        "with more detail and specifics. Build on what was already written."
    ),
)

inner_workflow = Workflow(
    name="Iterative Research",
    description="Researches a topic in iterative passes until sufficiently detailed",
    steps=[
        Loop(
            name="research_loop",
            steps=[Step(name="research_pass", agent=researcher)],
            end_condition=is_detailed_enough,
            max_iterations=3,
        ),
    ],
)

# --- Outer workflow ---
writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Write a polished summary from the detailed research provided.",
)

outer_workflow = Workflow(
    name="Iterative Research and Write",
    description="Iteratively researches until detailed, then writes a summary",
    steps=[
        Step(name="research_phase", workflow=inner_workflow),
        Step(name="writing_phase", agent=writer),
    ],
)


if __name__ == "__main__":
    outer_workflow.print_response(
        input="Explain how neural networks learn",
        stream=True,
    )
