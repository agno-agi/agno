"""
Bounding The Kept Tail By Size
=============================

`keep_last_runs` says how many turns survive a fold. It does not say how large they
are - and compaction only folds what sits in FRONT of the kept tail, so a verbose
turn landing inside the tail is one it can never bring back down.

`keep_last_tokens` bounds the tail's size instead. On five detailed turns of roughly
4,700 tokens each:

    keep_last_runs=2      fold 14,178  tail 9,452   ratio 1.50  -> declined
    keep_last_tokens=2000 fold 18,929  tail 4,701   ratio 4.03  -> folds

Both kept "the recent conversation". The run count kept two enormous turns, which left
too little in front of them for the fold to pay for its summary - so nothing happened
and all 23,630 tokens stayed. The token budget kept one, and the fold went through.

The two are mutually exclusive - they describe the same tail in different units, so
setting both raises rather than silently picking a winner.

The cut still snaps to a turn boundary, so a tool call is never severed from its
result. That means the tail can come out somewhat larger than the budget: it is a
target, not a hard cap.

Reach for `keep_last_tokens` when turns vary a lot in length, which is most
tool-calling agents. `keep_last_runs` is simpler and fine when turns are uniform.

Prerequisites: OPENAI_API_KEY, and a local Postgres (./cookbook/scripts/run_pgvector.sh)
Run: .venvs/demo/bin/python cookbook/02_agents/03_context_management/compaction/compaction_tail_budget.py
"""

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
compaction = Compaction(
    compact_at_tokens=8_000,
    # The tail is bounded by size, not by turn count.
    keep_last_tokens=2_000,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    session_id="compaction_tail_budget",
    add_history_to_context=True,
    compaction=compaction,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Short questions, then one that asks for far more - the shape a run count
    # cannot bound, because the large turn lands inside the tail.
    # Every turn is substantial. Short early turns would leave nothing worth folding -
    # the fold has to be large enough to pay for the summary replacing it.
    questions = [
        "Explain how B-tree indexes work, in full detail, with worked examples.",
        "Explain hash indexes and how they differ, in full detail.",
        "Explain covering indexes and index-only scans, in full detail.",
        "Explain when an index hurts more than it helps, in full detail.",
        "Explain index maintenance and fragmentation, in full detail.",
    ]

    for question in questions:
        agent.print_response(question)
        run = agent.get_last_run_output(session_id="compaction_tail_budget")
        if run is not None and run.compaction is not None:
            r = run.compaction
            print(
                f"\n[compacted {r.messages_compacted} messages: {r.tokens_before} -> {r.tokens_after} tokens]"
            )

    # Compaction shortens the request, never the record.
    session = agent.get_session(session_id="compaction_tail_budget")
    stored = sum(len(run.messages or []) for run in session.runs or [])
    print(f"\nMessages still stored in the session: {stored}")
