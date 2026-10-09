"""
Jev Async
=========

Triage several tickets concurrently with `adecide`. Each call answers every
question in one request, so the batch takes about as long as one ticket.
"""

import asyncio

from agno.models.decision import Choice, Noul
from agno.models.typesafe import Jev

# ---------------------------------------------------------------------------
# Create Model
# ---------------------------------------------------------------------------

jev = Jev()

questions = {
    "urgent": Noul(instructions="Does the customer need this resolved today?"),
    "area": Choice(
        instructions="Which team owns this ticket?",
        options=["billing", "technical", "sales"],
    ),
}

tickets = [
    "I was charged twice for my October invoice.",
    "Your API has returned 503 for every request since 9am.",
    "Do you offer a discount for nonprofits?",
]


async def triage_all() -> None:
    results = await asyncio.gather(
        *(jev.adecide(state=t, questions=questions) for t in tickets)
    )
    for ticket, result in zip(tickets, results):
        print(ticket)
        print(f"  area={result['area'].value} urgent={result['urgent'].value}")


# ---------------------------------------------------------------------------
# Run Model
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(triage_all())
