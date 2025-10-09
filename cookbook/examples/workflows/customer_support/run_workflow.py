from typing import Any, Dict

from agents import (
    SupportTicketClassification,
    support_agent,
    triage_agent,
)
from agno.utils.log import log_info
from agno.workflow import Step, StepInput, StepOutput, Workflow


def cache_lookup_step(
    step_input: StepInput, session_state: Dict[str, Any]
) -> StepOutput:
    """Step 1: Check if we have a cached solution for this query"""
    query = step_input.input

    cached_solution = session_state.get("solutions", {}).get(query)
    if cached_solution:
        log_info(f"Cache hit! Returning cached solution for query: {query}")
        return StepOutput(content=cached_solution, stop=True)

    log_info(f"No cached solution found for query: {query}")
    return StepOutput(
        content=query,
    )


def triage_step(step_input: StepInput) -> StepOutput:
    """Step 2: Classify and analyze the customer query"""
    query = step_input.input

    classification_response = triage_agent.run(query)
    classification = classification_response.content

    assert isinstance(classification, SupportTicketClassification)

    log_info(f"Classification: {classification.model_dump_json()}")

    return StepOutput(
        content=classification,
    )


def cache_storage_step(
    step_input: StepInput, session_state: Dict[str, Any]
) -> StepOutput:
    """Step 4: Cache the solution for future use"""
    query = step_input.input
    solution = step_input.get_last_step_content()

    # Initialize solutions cache if not exists
    if "solutions" not in session_state:
        session_state["solutions"] = {}

    # Cache the solution
    session_state["solutions"][query] = solution
    log_info(f"Cached solution for query: {query}")

    return StepOutput(content=solution)


# Create the customer support workflow with multiple steps
customer_support_workflow = Workflow(
    name="Customer Support Resolution Pipeline",
    description="AI-powered customer support with intelligent caching and multi-step processing",
    steps=[
        Step(name="Cache Lookup", executor=cache_lookup_step),
        Step(name="Query Triage", executor=triage_step),
        Step(name="Solution Generation", agent=support_agent),
        Step(name="Cache Storage", executor=cache_storage_step),
    ],
)


if __name__ == "__main__":
    test_queries = [
        "I can't log into my account, forgot my password",
        "How do I reset my password?",
        "My billing seems wrong, I was charged twice",
        "The app keeps crashing when I upload files",
        "I can't log into my account, forgot my password",  # repeat query
    ]

    for i, query in enumerate(test_queries, 1):
        response = customer_support_workflow.run(input=query)
