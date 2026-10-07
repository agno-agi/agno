"""
Perplexity Decisions
====================

The same ticket triage as `typesafe/basic.py`, on Perplexity's Decisions API.
Swapping decision models is a one-line change.
"""

from agno.models.decision import Choice, Noul, Score
from agno.models.perplexity import PerplexityDecisions

# ---------------------------------------------------------------------------
# Create Model
# ---------------------------------------------------------------------------

model = PerplexityDecisions()

questions = {
    "urgent": Noul(instructions="Does the customer need this resolved today?"),
    "area": Choice(
        instructions="Which team owns this ticket?",
        options=["billing", "technical", "sales"],
    ),
    "severity": Score(
        instructions="How badly is the product affected?",
        levels=["Cosmetic", "Degraded", "Outage"],
    ),
}

# ---------------------------------------------------------------------------
# Run Model
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = model.decide(
        state="Checkout has returned 500 errors for an hour and our sale launches tomorrow morning.",
        questions=questions,
    )
    for name, answer in result.items():
        print(f"{name}: {answer.value}")
