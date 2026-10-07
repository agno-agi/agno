"""
OpenAI Decisions
================

The same ticket triage as `typesafe/basic.py`, on OpenAI's Decisions API.
Agno translates the questions into OpenAI's format and the answers back.
"""

import asyncio

from agno.models.decision import Choice, Noul, Score
from agno.models.openai import OpenAIDecisions

# ---------------------------------------------------------------------------
# Create Model
# ---------------------------------------------------------------------------

model = OpenAIDecisions(id="gpt-6-luna")

questions = {
    "urgent": Noul(instructions="Does the customer need this resolved today?"),
    "area": Choice(
        instructions="Which team owns this ticket?",
        options={
            "billing": "Payments, invoices, refunds",
            "technical": "Bugs, outages, errors",
            "sales": None,
        },
    ),
    "severity": Score(
        instructions="How badly is the product affected?",
        levels=["Cosmetic", "Degraded", "Outage"],
    ),
}

ticket = "Checkout has returned 500 errors for an hour and our sale launches tomorrow morning."

# ---------------------------------------------------------------------------
# Run Model
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    result = model.decide(state=ticket, questions=questions)
    for name, answer in result.items():
        print(f"{name}: {answer.value}")

    # --- Async ---
    result = asyncio.run(model.adecide(state=ticket, questions=questions))
    print(f"Area probabilities: {result['area'].probabilities}")
