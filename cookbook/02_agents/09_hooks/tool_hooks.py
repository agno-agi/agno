"""
Tool Hooks
=============================

Use tool_hooks to add middleware that wraps every tool call.

Tool hooks act as middleware: each hook receives the tool name, arguments,
and a next_func callback. The hook must call next_func(**args) to continue
the chain, and can inspect or modify args before and the result after.
"""

import time

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools


def timing_hook(function_name: str, func: callable, args: dict):
    """Measure and print the execution time of each tool call."""
    start = time.time()
    result = func(**args)
    elapsed = time.time() - start
    print(f"[timing_hook] {function_name} took {elapsed:.3f}s")
    return result


def logging_hook(function_name: str, func: callable, args: dict):
    """Log the tool name and arguments before execution."""
    print(f"[logging_hook] Calling {function_name} with args: {list(args.keys())}")
    return func(**args)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[WebSearchTools()],
    # Hooks are applied to every tool call in middleware order
    tool_hooks=[logging_hook, timing_hook],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What is the current population of Tokyo?",
        stream=True,
    )
