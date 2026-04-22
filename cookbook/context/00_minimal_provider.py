"""
Minimal Custom ContextProvider
==============================

Shows the smallest possible ContextProvider: an in-memory dict of
quotes by author. No external deps, no services. Demonstrates what
scaffolding is needed to plug a new source into an agno.Agent via
`provider.get_tools()`.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context import Answer, ContextProvider, Status
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# A toy data source: quotes keyed by author
# ---------------------------------------------------------------------------
QUOTES: dict[str, list[str]] = {
    "hopper": [
        "The most dangerous phrase in the language is 'we've always done it this way'.",
        "A ship in port is safe, but that's not what ships are built for.",
    ],
    "feynman": [
        "The first principle is that you must not fool yourself — and you are the easiest person to fool.",
        "What I cannot create, I do not understand.",
    ],
    "mccarthy": [
        "Premature optimization is the root of all evil.",
    ],
}


# ---------------------------------------------------------------------------
# Subclass ContextProvider — implement aquery() + astatus()
# ---------------------------------------------------------------------------
class QuotesContextProvider(ContextProvider):
    """Toy provider — returns any quotes matching the question case-insensitively."""

    def status(self) -> Status:
        return Status(ok=True, detail=f"{sum(len(v) for v in QUOTES.values())} quotes")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str) -> Answer:
        q = question.lower()
        hits: list[str] = []
        for author, quotes in QUOTES.items():
            if author in q:
                hits.extend(f"{author}: {text}" for text in quotes)
        for quotes in QUOTES.values():
            for text in quotes:
                if any(word in text.lower() for word in q.split() if len(word) > 3):
                    line = f"(match): {text}"
                    if line not in hits:
                        hits.append(line)
        return Answer(text="\n".join(hits) if hits else "no matching quotes")

    async def aquery(self, question: str) -> Answer:
        return self.query(question)


# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
provider = QuotesContextProvider(id="quotes", name="Quotes")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=provider.get_tools(),
    instructions=(
        provider.instructions()
        + "\nWhen a user asks about a person, always query the tool first. "
        "Quote the exact text you find — don't paraphrase."
    ),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    prompt = "Any quotes from Hopper about how things are done?"
    print(f"\n> {prompt}\n")
    # Context tools are async, so use aprint_response under asyncio.run
    asyncio.run(agent.aprint_response(prompt))
