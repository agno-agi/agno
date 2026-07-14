"""
Per-Tool Call Limit
===================

This cookbook shows how to limit one tool without preventing other tools from
running in the same Agent run.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import tool


@tool(max_calls=1)
def search_docs(query: str) -> str:
    """Search a small, deterministic documentation index."""
    return f"Documentation result for: {query}"


@tool
def log_status(message: str) -> str:
    """Record what happened after the limited tool was called."""
    return f"Status recorded: {message}"


agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[search_docs, log_status],
    tool_call_limit=4,
    instructions=[
        "Call search_docs twice with different queries.",
        "After the second search_docs call is blocked, call log_status once.",
        "Then explain which calls ran and which call was blocked.",
    ],
)


if __name__ == "__main__":
    agent.print_response(
        "Search the docs for 'agents' and then 'teams'. Record the result after both attempts.",
        stream=True,
    )
