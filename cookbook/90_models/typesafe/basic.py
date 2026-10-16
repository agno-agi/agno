"""
Jev Basic
=========

Classify a support message by department, urgency, and customer frustration.
Boolean decisions use explicit probability thresholds. Frustration is a
fractional score from 0 (calm) to 2 (furious), rather than a rounded enum.

Requires Python 3.10+, typesafe-sdk, and TYPESAFE_API_KEY.
"""

from typing import Annotated, Literal

from pydantic import BaseModel
from rich.pretty import pprint
from typesafe_sdk import Choice, Noul, Score

from agno.agent import Agent
from agno.models.typesafe import Jev, JevField


class Triage(BaseModel):
    department: Annotated[
        Literal["billing", "technical", "sales"],
        JevField(
            Choice(
                instructions="Which team should handle the message in state.input?",
                criteria={
                    "billing": "Charges, refunds, invoices and payment methods",
                    "technical": "Bugs, outages, errors and integrations",
                    "sales": "Pricing questions, upgrades and new accounts",
                },
            )
        ),
    ]
    is_urgent: Annotated[
        bool,
        JevField(
            Noul(instructions="Does state.input convey urgency or time pressure?"),
            threshold=0.7,
        ),
    ]
    frustration: Annotated[
        float,
        JevField(
            Score(
                instructions="How frustrated does the customer in state.input appear?",
                criteria=[
                    "Calm, just stating facts",
                    "Frustrated but civil",
                    "Very angry, strong language",
                ],
            )
        ),
    ]


agent = Agent(model=Jev(), output_schema=Triage, cache_session=True)

if __name__ == "__main__":
    # One request for each department: billing, technical, and sales.
    for request in (
        "I was charged twice for my subscription this month. Please refund the duplicate payment.",
        "I've been trying to connect my Stripe account for 3 days and the integration keeps failing. "
        "I'm losing sales. Please help ASAP.",
        "We're considering opening an account for our team. What plans do you offer for 20 users?",
    ):
        agent.print_response(request)
        response = agent.get_last_run_output()
        if response is not None:
            pprint(response.model_provider_data)
            pprint(response.metrics)
