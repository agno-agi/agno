"""Refresh a callable tool factory after each completed tool batch."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

state = {"unlocked": False}


def unlock_tools() -> str:
    """Unlock the follow-up tool for the next model step."""
    state["unlocked"] = True
    return "The follow-up tool is now available."


def follow_up_tool() -> str:
    """A tool that is only exposed after unlock_tools has run."""
    return "Follow-up tool completed."


def tools_factory():
    tools = [unlock_tools]
    if state["unlocked"]:
        tools.append(follow_up_tool)
    return tools


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=tools_factory,
    cache_callables=False,
    refresh_tools_per_step=True,
    instructions=[
        "Call unlock_tools first, then call follow_up_tool after it becomes available.",
    ],
)

agent.print_response("Run the two-step tool flow.")
