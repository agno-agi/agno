"""
Example demonstrating Router selector flexibility:
1. Return step name as string
2. Return Step object directly
3. Return List[Step] for chaining
4. Use step_choices parameter for dynamic selection
5. Support nested lists in choices (becomes Steps container)
"""

from typing import List, Union

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# =============================================================================
# Example 1: Return step name as string (simplest approach)
# =============================================================================

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


workflow_string_selector = Workflow(
    name="Expert Routing (String Selector)",
    steps=[
        Router(
            name="Topic Router",
            selector=route_by_topic,
            choices=[tech_step, business_step, general_step],
        ),
    ],
)

# =============================================================================
# Example 2: Using step_choices parameter for dynamic selection
# =============================================================================

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


workflow_step_choices = Workflow(
    name="Dynamic Routing (step_choices)",
    steps=[
        Router(
            name="Dynamic Router",
            selector=dynamic_selector,
            choices=[researcher, writer, reviewer],
        ),
    ],
)

# =============================================================================
# Example 3: Nested lists in choices (becomes Steps container)
# =============================================================================

step_a = Agent(name="step_a", model=OpenAIChat(id="gpt-4o-mini"), instructions="Step A")
step_b = Agent(name="step_b", model=OpenAIChat(id="gpt-4o-mini"), instructions="Step B")
step_c = Agent(name="step_c", model=OpenAIChat(id="gpt-4o-mini"), instructions="Step C")


def nested_selector(step_input: StepInput, step_choices: list) -> Union[str, Step, List[Step]]:
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


workflow_nested = Workflow(
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
    print("=" * 60)
    print("Example 1: String-based selector (returns step name)")
    print("=" * 60)
    workflow_string_selector.print_response("Tell me about AI trends", stream=True)

    print("\n" + "=" * 60)
    print("Example 2: step_choices parameter")
    print("=" * 60)
    workflow_step_choices.print_response("I need to research something", stream=True)

    print("\n" + "=" * 60)
    print("Example 3: Nested choices")
    print("=" * 60)
    workflow_nested.print_response("Run the sequence", stream=True)
