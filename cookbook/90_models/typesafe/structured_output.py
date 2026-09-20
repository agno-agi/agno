"""Jev: typed decisions from annotated Pydantic fields."""

from typing import Annotated, Literal

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul, Score

from agno.agent import Agent
from agno.models.typesafe import Jev, JevField
from agno.utils.pprint import pprint_run_response
from rich.pretty import pprint


class Ticket(BaseModel):
    message: str
    customer_tier: Literal["standard", "premium"]


class Triage(BaseModel):
    category: Annotated[
        Literal["billing", "technical"],
        JevField(
            Choice(
                instructions="Which category best fits state.input.message?",
                criteria={
                    "billing": "Payments, charges, refunds",
                    "technical": "Bugs, outages, configuration",
                },
            )
        ),
    ]
    urgent: Annotated[
        bool,
        JevField(
            Noul(instructions="Does the ticket require immediate attention?"),
            threshold=0.8,
        ),
    ]
    severity: Annotated[
        float,
        JevField(
            Score(
                instructions="Rate the impact of the reported issue.",
                criteria=[
                    "Minor inconvenience",
                    "Some work blocked",
                    "All work blocked",
                ],
            )
        ),
    ]


agent = Agent(
    model=Jev(),
    input_schema=Ticket,
    output_schema=Triage,
    instructions="Premium customers with blocked work require immediate attention.",
)

if __name__ == "__main__":
    response = agent.run(
        Ticket(
            message="Our workspace is completely unavailable", customer_tier="premium"
        )
    )
    pprint_run_response(response)
    pprint(response.model_provider_data)  # Raw probabilities, usage and request ID.
