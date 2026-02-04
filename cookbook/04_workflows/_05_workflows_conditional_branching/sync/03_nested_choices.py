"""
Example 3: Nested lists in choices (becomes Steps container)

When choices contains nested lists like [step_a, [step_b, step_c]],
the nested list becomes a Steps container that executes sequentially.
"""

from typing import List, Union

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

step_a = Agent(name="step_a", model=OpenAIChat(id="gpt-4o-mini"), instructions="Step A")
step_b = Agent(name="step_b", model=OpenAIChat(id="gpt-4o-mini"), instructions="Step B")
step_c = Agent(name="step_c", model=OpenAIChat(id="gpt-4o-mini"), instructions="Step C")


def nested_selector(
    step_input: StepInput, step_choices: list
) -> Union[str, Step, List[Step]]:
    """
    When choices contains nested lists like [step_a, [step_b, step_c]],
    the nested list becomes a Steps container in step_choices.
    """
    user_input = step_input.input.lower()

    # step_choices[0] = Step for step_a
    # step_choices[1] = Steps container with [step_b, step_c]

    if "single" in user_input:
        return step_choices[0]  # Just step_a
    else:
        return step_choices[1]  # Steps container with step_b -> step_c


workflow = Workflow(
    name="Nested Choices Routing",
    steps=[
        Router(
            name="Nested Router",
            selector=nested_selector,
            choices=[step_a, [step_b, step_c]],  # Nested list becomes Steps container
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response("Run the sequence", stream=True)
