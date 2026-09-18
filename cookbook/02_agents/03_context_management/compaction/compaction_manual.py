"""
Manual Compaction
=============================

`agent.compact()` folds the conversation now, rather than waiting for it to reach
`compact_at_tokens`. Useful at a natural seam: the end of a topic, or before handing
the agent a long task.

Compaction can legitimately decline, so this returns a result rather than raising.
A summary costs a few hundred tokens whatever it replaces, so folding a span smaller
than that would leave the context BIGGER - declining is the correct outcome, and the
status says which case you hit:

- `compacted`         - the fold happened; `record` carries the token counts
- `not_worth_it`      - the span is too small to pay for the summary replacing it
- `nothing_to_fold`   - the kept tail covers the whole conversation
- `already_compacted` - a previous fold already covers everything foldable
- `no_history`        - the session has no stored history yet
- `not_enabled`       - compaction is not configured on this agent
- `summary_failed`    - the summarizer returned nothing

The same result is what the AgentOS route returns as JSON:

    POST /agents/{agent_id}/sessions/{session_id}/compact
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
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    session_id="compaction_manual",
    add_history_to_context=True,
    # No automatic trigger at all: this session folds only when asked to.
    # keep_last_runs=1 because a fold still has to clear min_fold_ratio - calling
    # compact() does not override that, and a 2-turn tail would need twice as much
    # conversation in front of it before any fold could pay for itself.
    compaction=Compaction(compact_at_tokens=None, keep_last_runs=1),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for question in [
        "Explain database indexing in detail, with worked examples.",
        "Explain B-tree indexes in depth and when they are the right choice.",
        "Explain hash indexes and how they differ, in detail.",
        "Explain covering indexes and index-only scans, in detail.",
    ]:
        agent.print_response(question)

    # Fold at a seam of your choosing.
    result = agent.compact(session_id="compaction_manual")
    print(f"\nstatus : {result.status.value}")
    print(f"message: {result.message}")

    if result.compacted:
        print(f"tokens : {result.record.tokens_before} -> {result.record.tokens_after}")
    else:
        # Not an error - compaction decided folding would not help here.
        print("History was left unchanged.")

    # Calling again immediately declines: the previous fold already covers
    # everything foldable, and nothing new has been said since.
    again = agent.compact(session_id="compaction_manual")
    print(f"\nsecond call: {again.status.value} - {again.message}")
