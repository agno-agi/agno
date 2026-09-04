"""
Compaction Thresholds
=============================

Tuning when compaction fires and how much it keeps.

Any threshold left unset is not evaluated, and the first one to trip wins:
- `compact_at_tokens` - context size, measured from what the provider reported
- `compact_at_runs` - runs currently in context
- `compact_at_messages` - messages currently in context

A cheaper model can do the summarizing, which is usually the right call: the
work is mechanical and the main model never sees the transcript being condensed.
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
compaction = Compaction(
    # A small model is enough to summarize a transcript.
    model=OpenAIResponses(id="gpt-5-mini"),
    compact_at_tokens=1_000,
    # Keep the last two turns verbatim; everything older folds into the summary.
    keep_last_runs=2,
)

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
    session_id="compaction_thresholds",
    add_history_to_context=True,
    num_history_runs=100,
    compaction=compaction,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for question in [
        "Explain how a database index works, in detail.",
        "Now compare that to a hash index, in detail.",
        "Explain covering indexes and index-only scans, in detail.",
        "Explain when an index hurts more than it helps, in detail.",
    ]:
        agent.print_response(question)

    print(f"\nCompactions so far: {compaction.stats.compactions}")
    print(f"Messages compacted: {compaction.stats.messages_compacted}")
