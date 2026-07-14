"""
Anthropic Server Tools — Multi-Turn
====================================

Combines web_search, web_fetch, and code_execution in a multi-turn
conversation. Each follow-up depends on server tool blocks preserved
in history from the previous turn.

Run: .venvs/demo/bin/python cookbook/90_models/anthropic/server_tools_multi_turn.py
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-6",
        betas=["code-execution-2025-05-22"],
    ),
    tools=[
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 3},
        {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 3},
        {"type": "code_execution_20250522", "name": "code_execution"},
    ],
    db=InMemoryDb(),
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

if __name__ == "__main__":
    # Turn 1: Search
    agent.print_response("Search the web for the latest Python 3.14 release notes")

    # Turn 2: Fetch a link from the search results (depends on search history)
    agent.print_response(
        "Fetch the official Python docs link from those results and summarize the key changes"
    )

    # Turn 3: Code execution building on fetched content (depends on fetch history)
    agent.print_response(
        "Write Python code that demonstrates one of the new features you just found. Run it."
    )
