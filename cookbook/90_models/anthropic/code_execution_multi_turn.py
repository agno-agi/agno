"""
Anthropic Code Execution Multi-Turn
=====================================

Multi-turn code execution: runs code, then asks a follow-up that builds
on the previous execution results.
Requires server tool blocks to be preserved in conversation history.

Run: .venvs/demo/bin/python cookbook/90_models/anthropic/code_execution_multi_turn.py
"""

import asyncio

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-6",
        betas=["code-execution-2025-05-22"],
    ),
    tools=[
        {
            "type": "code_execution_20250522",
            "name": "code_execution",
        }
    ],
    db=InMemoryDb(),
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

if __name__ == "__main__":
    # --- Sync ---
    agent.print_response(
        "Write Python code to generate all prime numbers up to 50 and print them"
    )
    agent.print_response(
        "Now modify that code to also calculate and print the sum of those primes"
    )

    # --- Sync + Streaming ---
    agent.session_id = None
    agent.print_response(
        "Write Python code to generate all prime numbers up to 50 and print them",
        stream=True,
    )
    agent.print_response(
        "Now modify that code to also calculate and print the sum of those primes",
        stream=True,
    )

    # --- Async ---
    agent.session_id = None

    async def run_async():
        await agent.aprint_response(
            "Write Python code to generate all prime numbers up to 50 and print them"
        )
        await agent.aprint_response(
            "Now modify that code to also calculate and print the sum of those primes"
        )

    asyncio.run(run_async())

    # --- Async + Streaming ---
    agent.session_id = None

    async def run_async_stream():
        await agent.aprint_response(
            "Write Python code to generate all prime numbers up to 50 and print them",
            stream=True,
        )
        await agent.aprint_response(
            "Now modify that code to also calculate and print the sum of those primes",
            stream=True,
        )

    asyncio.run(run_async_stream())
