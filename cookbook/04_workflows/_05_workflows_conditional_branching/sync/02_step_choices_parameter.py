"""
Example 2: Using step_choices parameter for dynamic selection

The selector function can receive step_choices as a parameter, which contains
the prepared Step objects from Router.choices. This allows dynamic selection
based on available steps, which is useful when steps are defined in the UI.
"""

from typing import List, Union

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

researcher = Agent(
    name="researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a researcher.",
)

writer = Agent(
    name="writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a writer.",
)

reviewer = Agent(
    name="reviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a reviewer.",
)


def dynamic_selector(step_input: StepInput, step_choices: list) -> Union[str, Step, List[Step]]:
    """
    Selector receives step_choices - can select by name or return Step directly.
    step_choices contains the prepared Step objects from Router.choices.
    """
    user_input = step_input.input.lower()

    # Build name map from step_choices
    step_map = {s.name: s for s in step_choices if hasattr(s, "name") and s.name}

    print(f"Available steps: {list(step_map.keys())}")

    # Can return step name as string
    if "research" in user_input:
        return "researcher"

    # Can return Step object directly
    if "write" in user_input:
        return step_map.get("writer", step_choices[0])

    # Can return list of Steps for chaining
    if "full" in user_input:
        return [step_map["researcher"], step_map["writer"], step_map["reviewer"]]

    # Default
    return step_choices[0]


workflow = Workflow(
    name="Dynamic Routing (step_choices)",
    steps=[
        Router(
            name="Dynamic Router",
            selector=dynamic_selector,
            choices=[researcher, writer, reviewer],
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response("I need to research something", stream=True)
