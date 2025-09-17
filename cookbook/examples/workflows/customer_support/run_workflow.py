from agents import (
    support_agent,
    triage_agent,
)
from agno.utils.log import log_info
from agno.workflow import Workflow


def cache_solution(session_state, query: str, solution: str):
    if "solutions" not in session_state:
        session_state["solutions"] = {}
    session_state["solutions"][query] = solution


def customer_support_execution(session_state, query: str) -> str:
    cached_solution = session_state.get("solutions", {}).get(query)
    if cached_solution:
        log_info(f"Cache hit! Returning cached solution for query: {query}")
        return cached_solution

    log_info(f"No cached solution found for query: {query}")

    classification_response = triage_agent.run(query)
    classification = classification_response.content

    solution_context = f"""
    Customer Query: {query}

    Classification: {classification}

    Please provide a clear, step-by-step solution for this customer issue.
    Make sure to format it in a customer-friendly way with clear instructions.
    """

    solution_response = support_agent.run(solution_context)
    solution = solution_response.content

    cache_solution(session_state, query, solution)

    return solution


# Create the customer support workflow
customer_support_workflow = Workflow(
    name="Customer Support Resolution Pipeline",
    description="AI-powered customer support with intelligent caching",
    steps=customer_support_execution,
    session_state={},  # Initialize empty session state
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
        response = customer_support_workflow.run(query=query)
