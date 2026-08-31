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
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
compaction = Compaction(
    # A small model is enough to summarize a transcript.
    model=OpenAIResponses(id="gpt-5-mini"),
    compact_at_tokens=100_000,
    keep_last_runs=5,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction_thresholds.db"),
    session_id="compaction_thresholds",
    add_history_to_context=True,
    num_history_runs=100,
    compaction=compaction,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Explain how a database index works.")
    agent.print_response("Now compare that to a hash index.")

    print(f"\nCompactions so far: {compaction.stats.compactions}")
    print(f"Messages compacted: {compaction.stats.messages_compacted}")
