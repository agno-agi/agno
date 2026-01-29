"""
Example 4: Loop in choices (iterative refinement)

Router choices can include Loop components for iterative processing.
This example shows routing between a quick response, draft writing,
or an iterative refinement loop.
"""

from typing import List, Union

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.loop import Loop
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

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

quick_response = Step(
    name="quick_response",
    executor=lambda x: StepOutput(content=f"Quick answer: {x.input}"),
)

# Loop that refines content multiple times
refinement_loop = Loop(
    name="refinement_loop",
    steps=[Step(name="refine_step", agent=refiner)],
    max_iterations=2,
)


def loop_selector(step_input: StepInput, step_choices: list) -> Union[str, Step, List[Step]]:
    """
    Select between quick response, draft writing, or iterative refinement loop.
    step_choices contains: [quick_response Step, draft_writer Step, refinement Loop]
    """
    user_input = step_input.input.lower()

    # step_choices[0] = quick_response (Step)
    # step_choices[1] = draft_writer (Step)
    # step_choices[2] = refinement_loop (Loop)

    if "quick" in user_input:
        return step_choices[0]  # Quick response
    elif "refine" in user_input or "polish" in user_input:
        # Chain: write draft then refine it in a loop
        return [step_choices[1], step_choices[2]]
    else:
        return step_choices[1]  # Just write a draft


workflow = Workflow(
    name="Loop Choice Routing",
    steps=[
        Router(
            name="Content Router",
            selector=loop_selector,
            choices=[quick_response, draft_writer, refinement_loop],  # Loop as a choice
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response("Please refine and polish a blog post about Python", stream=True)
