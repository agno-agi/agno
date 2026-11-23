"""
Custom Context Provider
=======================

When a built-in provider doesn't fit, subclass `ContextProvider`. The
ABC handles tool wrapping, name derivation, and error shaping — you
only write `aquery` + `astatus`.

Here: a tiny FAQ source over an in-memory dict. The agent calls
`query_faq(question)` and gets the matching answer back.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context import Answer, ContextProvider, Status
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# The data
# ---------------------------------------------------------------------------
FAQ = {
    "return": "Returns accepted within 30 days. Email support@example.com.",
    "hours": "We're open Mon-Fri, 9am-5pm ET.",
    "shipping": "Orders ship in 2-3 business days via USPS.",
}


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------
class FAQContextProvider(ContextProvider):
    def status(self) -> Status:
        return Status(ok=True, detail=f"{len(FAQ)} entries")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str) -> Answer:
        key = next((k for k in FAQ if k in question.lower()), None)
        return Answer(text=FAQ[key] if key else "No FAQ entry matches that.")

    async def aquery(self, question: str) -> Answer:
        return self.query(question)


# ---------------------------------------------------------------------------
# Wire it into an agent
# ---------------------------------------------------------------------------
faq = FAQContextProvider(id="faq")
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=faq.get_tools(),
    instructions=faq.instructions(),
    markdown=True,
)


if __name__ == "__main__":
    asyncio.run(agent.aprint_response("What's your return policy?"))
