"""
Compaction Thresholds
=============================

Tuning when compaction fires and how much it keeps.

Size is the only automatic trigger. `compact_at_tokens` is measured from what the
provider reported for the last run, so it costs nothing to evaluate. A run or message
count is deliberately not offered: twenty short exchanges and twenty research turns
differ by orders of magnitude, so counting them fires on conversations far too small
to fold and stays quiet on ones that overflow.

Set `compact_at_tokens=None` to turn the automatic trigger off entirely and fold only
when you call `agent.compact()`.

The kept tail is set one of two ways, and they cannot both be used:

- `keep_last_runs` keeps whole turns. Simple, but a run count says how many turns
  survive, not how large they are - a few verbose turns produce a tail compaction
  cannot bring back down, because it only folds what sits in FRONT of the tail.
- `keep_last_tokens` bounds the tail's size instead. The cut still snaps to a turn
  boundary rather than severing a tool call from its result, so the tail can come out
  somewhat larger than asked - it is a budget, not a hard cap.

Reach for `keep_last_tokens` when turns vary a lot in length, which is most
tool-calling agents.

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
    keep_last_runs=1,
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
