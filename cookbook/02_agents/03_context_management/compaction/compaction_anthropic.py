"""
Compaction With Anthropic
=============================

Compaction is provider-agnostic: it rewrites the message list, not the request
format, so the same folding works on Claude as on OpenAI.

One difference is worth knowing. OpenAI's Responses API can continue a
conversation by id (`previous_response_id`), which means the server replays
history the request never sent - so compaction has to sever that chain, or the
saving is imaginary. Anthropic has no such mechanism: every request carries its
own history, so what compaction sends is exactly what the model sees.

Prerequisites: ANTHROPIC_API_KEY, and a Postgres running on localhost:5532
Run: .venvs/demo/bin/python cookbook/02_agents/03_context_management/compaction/compaction_anthropic.py
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
compaction = Compaction(compact_at_runs=4, keep_last_runs=1)

agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    db=db,
    session_id="compaction_anthropic",
    add_history_to_context=True,
    num_history_runs=100,
    compaction=compaction,
    instructions=[
        "Answer thoroughly - long answers grow the context, which is the point here."
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for question in [
        "Explain how B-tree indexes work, in detail.",
        "Explain hash indexes and how they differ, in detail.",
        "Explain covering indexes and index-only scans, in detail.",
        "Explain when an index hurts more than it helps, in detail.",
        "Summarize the trade-offs we covered.",
    ]:
        agent.print_response(question)
        run = agent.get_last_run_output(session_id="compaction_anthropic")
        if run is not None and run.compaction is not None:
            r = run.compaction
            print(
                f"\n[compacted {r.messages_compacted} messages: {r.tokens_before} -> {r.tokens_after} tokens]"
            )

    print(f"\nCompactions: {compaction.stats.compactions}")
