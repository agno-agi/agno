"""
Async Compaction
=============================

Compaction works the same way on the async path - the summary is generated with
`aresponse` and the archive is written through the filesystem's async surface.
"""

import asyncio

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
compaction = Compaction(compact_at_runs=4, keep_last_runs=2)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction_async.db"),
    session_id="compaction_async",
    add_history_to_context=True,
    num_history_runs=100,
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

    print(f"\nCompactions: {compaction.stats.compactions}")


if __name__ == "__main__":
    asyncio.run(main())
