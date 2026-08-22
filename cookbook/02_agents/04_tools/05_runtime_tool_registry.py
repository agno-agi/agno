"""Register a tool during a run and expose it on the next model step."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import ToolRegistry

registry = ToolRegistry()


def follow_up_tool() -> str:
    """A tool that becomes available after the unlock tool runs."""
    return "Follow-up tool completed."


def unlock_tools() -> str:
    """Register the follow-up tool for the next model step."""
    registry.register(follow_up_tool)
    return "The follow-up tool is now available."


registry.register(unlock_tools)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=registry,
    instructions=["Call unlock_tools first, then call follow_up_tool."],
)

agent.print_response("Run the two-step tool flow.")
