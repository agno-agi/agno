"""
Perplexity Decisions Agent
==========================

The triage agent from `typesafe/agent_triage.py` on Perplexity's Decisions API.
Swapping the decision model behind an Agent is a one-line change.
"""

from typing import Literal

from agno.agent import Agent
from agno.models.perplexity import PerplexityDecisions
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define the Output
# ---------------------------------------------------------------------------


class Ticket(BaseModel):
    """Triage a customer support ticket."""

    area: Literal["billing", "technical", "sales"] = Field(
        description="Which team owns this ticket"
    )
    urgent: bool = Field(
        description="The customer is losing money or has a deadline today"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=PerplexityDecisions(), output_schema=Ticket)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run = agent.run("I was charged twice for my October invoice.")
    print(run.content)
    print(run.decisions)
