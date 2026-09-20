"""Use official SDK questions directly, without an output schema."""

from typesafe_sdk import Choice, Noul

from agno.agent import Agent
from agno.models.typesafe import Jev

agent = Agent(
    model=Jev(
        questions={
            "department": Choice(
                instructions="Choose the department for state.input.",
                criteria={
                    "billing": "Payments and refunds",
                    "technical": "Bugs and outages",
                },
            ),
            "urgent": Noul(
                instructions="Does the request describe work that is completely blocked?"
            ),
        }
    ),
)

if __name__ == "__main__":
    agent.print_response("I was charged twice for my subscription")
