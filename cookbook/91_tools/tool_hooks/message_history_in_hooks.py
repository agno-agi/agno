"""
Message History In Hooks
=============================

Access the current run's message history inside tool pre/post hooks
via run_context.messages.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.base import RunContext
from agno.tools import FunctionCall, tool

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


def pre_hook(run_context: RunContext, fc: FunctionCall):
    msgs = run_context.messages
    count = len(msgs) if msgs else 0
    print(f"[pre-hook] {fc.function.name} - {count} messages in run")


def post_hook(run_context: RunContext, fc: FunctionCall):
    msgs = run_context.messages
    count = len(msgs) if msgs else 0
    print(
        f"[post-hook] {fc.function.name} returned '{fc.result}' - {count} messages in run"
    )


@tool(pre_hook=pre_hook, post_hook=post_hook)
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Sunny, 72F in {city}"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_weather],
    instructions=["Use the tools to help the user."],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the weather in San Francisco?")
