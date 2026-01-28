"""
Example demonstrating how to use step_choices parameter in Router selector.

The selector function receives the prepared steps (step_choices) so it can
dynamically select which steps to execute based on the available choices.
This is useful when steps are defined in the UI and the selector needs to
access them at runtime.
"""

from typing import List

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow


# Selector function that receives step_choices as a parameter
def my_selector(step_input: StepInput, step_choices: List[Step]) -> List[Step]:
    """
    Select steps based on input and available step choices.

    Args:
        step_input: The input to the router
        step_choices: List of prepared Step objects available for selection
    """
    user_input = step_input.input.lower()
    step_map = {step.name: step for step in step_choices if step.name}

    print(f"Input: {step_input.input}")
    print(f"Available steps: {list(step_map.keys())}")

    # Route based on intent keywords
    if any(word in user_input for word in ["research", "find", "search", "look up", "investigate"]):
        if "researcher" in step_map:
            return [step_map["researcher"]]

    if any(word in user_input for word in ["write", "draft", "compose", "create content"]):
        if "writer" in step_map:
            return [step_map["writer"]]

    if any(word in user_input for word in ["review", "check", "evaluate", "feedback"]):
        if "reviewer" in step_map:
            return [step_map["reviewer"]]

    # For complex tasks, chain multiple steps
    if any(word in user_input for word in ["article", "blog", "report"]):
        chain = []
        for name in ["researcher", "writer", "reviewer"]:
            if name in step_map:
                chain.append(step_map[name])
        if chain:
            return chain

    # Default: return first available step
    return [step_choices[0]] if step_choices else []


if __name__ == "__main__":
    # Define some agents as steps
    researcher = Agent(
        name="researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher. Research the given topic.",
    )

    writer = Agent(
        name="writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a writer. Write about the given topic.",
    )

    reviewer = Agent(
        name="reviewer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a reviewer. Review the given content.",
    )

    # Create a router with step_choices-aware selector
    router = Router(
        name="dynamic_router",
        selector=my_selector,
        choices=[researcher, writer, reviewer],
    )

    # Create workflow with the router
    workflow = Workflow(
        name="dynamic_workflow",
        steps=[router],
    )

    # Test 1: Research intent -> selects researcher
    print("\n--- Test 1: Research intent ---")
    result = workflow.print_response("Find information about AI trends", stream=True)

    # Test 2: Writing intent -> selects writer
    print("\n--- Test 2: Writing intent ---")
    result = workflow.print_response("Write a summary about machine learning", stream=True)

    # Test 3: Review intent -> selects reviewer
    print("\n--- Test 3: Review intent ---")
    result = workflow.print_response("Review this document for errors", stream=True)

    # Test 4: Complex task -> chains researcher, writer, reviewer
    print("\n--- Test 4: Complex task (article) ---")
    result = workflow.print_response("Create an article about quantum computing", stream=True)

    # Test 5: No matching intent -> defaults to first step
    print("\n--- Test 5: Default fallback ---")
    result = workflow.print_response("Hello there", stream=True)
