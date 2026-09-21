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
    # One request for each department: billing and technical.
    for request in (
        "I was charged twice for my subscription",
        "Our workspace returns a 500 error and nobody can log in. All work is blocked.",
    ):
        agent.print_response(request)
