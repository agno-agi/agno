"""
Loop In Choices
===============

Demonstrates using a `Loop` component as one of the router choices.
"""

from typing import List, Union

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.loop import Loop
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
draft_writer = Agent(
    name="draft_writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write a draft on the given topic. Keep it concise.",
)

refiner = Agent(
    name="refiner",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Refine and improve the given draft. Make it more polished.",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
quick_response = Step(
    name="quick_response",
    executor=lambda x: StepOutput(content=f"Quick answer: {x.input}"),
)

refinement_loop = Loop(
    name="refinement_loop",
    steps=[Step(name="refine_step", agent=refiner)],
    max_iterations=2,
)


# ---------------------------------------------------------------------------
# Define Router Selector
# ---------------------------------------------------------------------------
def loop_selector(
    step_input: StepInput,
    step_choices: list,
) -> Union[str, Step, List[Step]]:
    user_input = step_input.input.lower()

    if "quick" in user_input:
        return step_choices[0]
    if "refine" in user_input or "polish" in user_input:
        return [step_choices[1], step_choices[2]]
    return step_choices[1]


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Loop Choice Routing",
    steps=[
        Router(
            name="Content Router",
            selector=loop_selector,
            choices=[quick_response, draft_writer, refinement_loop],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    workflow.print_response(
        "Please refine and polish a blog post about Python",
        stream=True,
    )
