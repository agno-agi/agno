"""
Jev Basic
=========

Ask Jev three typed questions about a support ticket in one request:
a yes/no (Noul), a pick-one (Choice) and a rating (Score).
"""

from agno.models.decision import Choice, Noul, Score
from agno.models.typesafe import Jev

# ---------------------------------------------------------------------------
# Create Model
# ---------------------------------------------------------------------------

jev = Jev()

questions = {
    "urgent": Noul(
        instructions="Does the customer need this resolved today?",
        yes="They are losing money or have a deadline today",
        no="It can wait its turn in the queue",
    ),
    "area": Choice(
        instructions="Which team owns this ticket?",
        options={
            "billing": "Payments, invoices, refunds",
            "technical": "Bugs, outages, errors",
            "sales": "Pricing, plans, upgrades",
        },
    ),
    "severity": Score(
        instructions="How badly is the product affected?",
        levels={
            "Cosmetic": "Appearance only, nothing is broken",
            "Degraded": "A task fails but a workaround exists",
            "Outage": "Customers cannot use the product",
        },
    ),
}

ticket = "Checkout has returned 500 errors for an hour and our sale launches tomorrow morning."

# ---------------------------------------------------------------------------
# Run Model
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = jev.decide(state=ticket, questions=questions)

    print(f"Urgent: {result['urgent'].value} (p={result['urgent'].probability:.2f})")
    print(f"Area: {result['area'].value} {result['area'].probabilities}")
    print(
        f"Severity: {result['severity'].label} (score={result['severity'].value:.2f})"
    )
    print(f"Input tokens: {result.metrics.input_tokens if result.metrics else 0}")
