"""
Compaction With A Searchable Archive
=============================

`searchable=True` gives the agent read-only search over its own archived
history, which changes what a summary is for. Normally a summary replaces the
conversation, so any detail it left out is gone. Here the originals are still
stored, so the summary works as an index and the agent can go read the rest.

The flow is summary-first, archive-as-fallback. When a summary is enough the
agent answers from it. When the question needs a detail the summary could not
keep, the agent calls `search_compacted_history` and reads it from the archive.

This example makes that fallback happen every time. It shares a 30-row parts
list, folds it away under a deliberately small summary budget - no summary of
that size can carry 30 rows - and then asks for a single row. The run prints
the search the agent made, so you can see where the answer came from.

`searchable` is on by default whenever `archive` is; it is set here to make the
example explicit.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------
compaction = Compaction(
    searchable=True,
    # Fold only when this example says so, so every run folds at the same point.
    compact_at_tokens=None,
    # Keep only the most recent turn verbatim; everything before it is folded.
    uncompacted_runs=1,
    # A summary this small cannot carry a 30-row table, so the rows have to be
    # looked up in the archive - which is what this example demonstrates.
    summary_budget_tokens=150,
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
    # A fresh session per run, so an earlier run's history cannot change this one.
    session_id=f"compaction_searchable_{uuid4().hex[:8]}",
    add_history_to_context=True,
    compaction=compaction,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Share a detailed list. Values a model cannot guess, so a correct answer
    #    can only have come from the archive.
    parts = "\n".join(
        f"part {i}: {['valve', 'gasket', 'bearing', 'seal', 'flange'][i % 5]}, "
        f"supplier {['Acme', 'Globex', 'Initech', 'Umbrella', 'Hooli'][i % 5]}, "
        f"lot {i * 7919 % 100000:05d}"
        for i in range(1, 31)
    )
    agent.print_response(f"Here is our parts list for later. Just say noted.\n{parts}")

    # 2. A turn after it, so there is history in front of the kept tail to fold.
    agent.print_response("In one sentence: what is a bill of materials?")

    # 3. Fold now. The parts list leaves the context; only a short summary and the
    #    archived original remain.
    result = agent.compact(session_id=agent.session_id)
    print(f"\n[{result.status.value}] {result.message}")

    # 4. Ask for one row. The summary cannot have it, so the agent searches - the
    #    search_compacted_history call shows up in the output below.
    agent.print_response(
        "What is the lot number of part 23 in the parts list I shared?"
    )

    run = agent.get_last_run_output()
    searches = [
        tool.tool_args.get("pattern")
        for tool in (run.tools if run else None) or []
        if tool.tool_name == "search_compacted_history"
    ]
    print(f"\nArchive searches: {searches}")
    print(f"Expected lot number: {23 * 7919 % 100000:05d}")
