"""One finite tool dispatch; its result is the final response."""

from typing import Literal

from agno.agent import Agent
from agno.models.typesafe import Jev


def select_support_queue(
    queue: Literal["billing", "technical"], urgent: bool = False
) -> str:
    """Select a support queue and urgency for the ticket."""
    return f"Selected queue: {queue}; urgent: {urgent}"


agent = Agent(model=Jev(mode="tools"), tools=[select_support_queue])

if __name__ == "__main__":
    agent.print_response("My account is inaccessible and all work is blocked")
