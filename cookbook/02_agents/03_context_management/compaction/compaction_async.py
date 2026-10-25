"""
Async Compaction
=============================

Compaction works the same way on the async path - the summary is generated with
`aresponse`, so a fold never blocks the event loop, and the folded messages are archived
in the agent's database alongside the session.
"""

import asyncio

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Keep only the latest turn verbatim, so a short demo has something in front of it to fold.
compaction = Compaction(uncompacted_runs=1)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    session_id="compaction_async",
    add_history_to_context=True,
    compaction=compaction,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    questions = [
        "Explain the CAP theorem in detail, with worked examples.",
        "Explain partition tolerance in depth and why it is not optional.",
        "Compare AP and CP databases in detail, with named systems.",
        "Explain consistency models in detail: linearizable to eventual.",
        "Which model would you pick for a payments ledger, and why?",
    ]
    for question in questions:
        await agent.aprint_response(question)

    # The async counterpart of agent.compact(), returning the same CompactionResult.
    result = await agent.acompact(session_id=agent.session_id)
    print(f"\n[{result.status.value}] {result.message}")

    print(f"Compactions: {compaction.stats.compactions}")


if __name__ == "__main__":
    asyncio.run(main())
