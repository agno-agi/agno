"""
Jev Triage Agent
================

An Agent whose model is a decision model. Each field of `output_schema` becomes
one typed question, all answered in a single request: `run.content` is the
filled `Ticket`, and `run.decisions` holds the probabilities behind each field.
"""

import asyncio
from typing import Literal

from agno.agent import Agent
from agno.models.decision import Choice, Score
from agno.models.typesafe import Jev
from pydantic import BaseModel, Field
from typing_extensions import Annotated

# ---------------------------------------------------------------------------
# Define the Output
# ---------------------------------------------------------------------------


class Ticket(BaseModel):
    """Triage a customer support ticket."""

    area: Annotated[
        Literal["billing", "technical", "sales"],
        Choice(
            options={
                "billing": "Payments, invoices, refunds",
                "technical": "Bugs, outages, errors",
                "sales": "Pricing, plans, upgrades",
            }
        ),
    ] = Field(description="Which team owns this ticket")
    urgent: bool = Field(
        description="The customer is losing money or has a deadline today"
    )
    severity: Annotated[
        int,
        Score(
            levels={
                "Cosmetic": "Appearance only, nothing is broken",
                "Degraded": "A task fails but a workaround exists",
                "Outage": "Customers cannot use the product",
            }
        ),
    ] = Field(description="How badly the product is affected")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Jev(), output_schema=Ticket)

ticket = "Checkout has returned 500 errors for an hour and our sale launches tomorrow morning."

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    run = agent.run(ticket)
    print(run.content)
    for name, answer in (run.decisions or {}).items():
        print(f"{name}: {answer}")

    # --- Async ---
    run = asyncio.run(agent.arun(ticket))
    print(run.content)
