"""
Example 1: Return step name as string (simplest approach)

The selector function can return a step name as a string, and the Router
will resolve it to the actual Step object from choices.
"""

from typing import List, Union

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

tech_expert = Agent(
    name="tech_expert",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a tech expert. Provide technical analysis.",
)

biz_expert = Agent(
    name="biz_expert",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a business expert. Provide business insights.",
)

generalist = Agent(
    name="generalist",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a generalist. Provide general information.",
)

tech_step = Step(name="Tech Research", agent=tech_expert)
business_step = Step(name="Business Research", agent=biz_expert)
general_step = Step(name="General Research", agent=generalist)


def route_by_topic(step_input: StepInput) -> Union[str, Step, List[Step]]:
    """Selector can return step name as string - Router resolves it."""
    topic = step_input.input.lower()

    if "tech" in topic or "ai" in topic or "software" in topic:
        return "Tech Research"  # Return name as string
    elif "business" in topic or "market" in topic or "finance" in topic:
        return "Business Research"  # Return name as string
    else:
        return "General Research"  # Return name as string


workflow = Workflow(
    name="Expert Routing (String Selector)",
    steps=[
        Router(
            name="Topic Router",
            selector=route_by_topic,
            choices=[tech_step, business_step, general_step],
        ),
    ],
)

if __name__ == "__main__":
    workflow.print_response("Tell me about AI trends", stream=True)
