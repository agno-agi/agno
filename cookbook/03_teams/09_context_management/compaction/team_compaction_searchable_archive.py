"""
Team Compaction With A Searchable Archive
=============================

The messages a fold replaces are stored as they were, and the team leader gets a
`search_compacted_history` tool over them. The summary works as an index: when a
question needs a detail the summary did not keep, the leader searches the archive.

This example makes that happen. It shares a 30-row parts list, folds it away
under a small summary budget that cannot carry 30 rows, and then asks for one
row. The run prints the search the leader made.

A Team and its members share one session. Each searches only its own folds: the
leader never reads a member's, and a member never reads the leader's.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
session_id = f"team_compaction_archive_{uuid4().hex[:8]}"

team = Team(
    name="Parts Desk",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[
        Agent(
            name="Pricing Analyst",
            role="Works out order totals",
            model=OpenAIResponses(id="gpt-5.6-luna"),
        )
    ],
    db=db,
    session_id=session_id,
    add_history_to_context=True,
    compaction=Compaction(
        compact_at_tokens=None,
        uncompacted_runs=1,
        # Too small to carry the parts list, so the detail has to come from the archive.
        compacted_token_budget=150,
        store_compacted_messages=True,
        search_compacted_messages=True,
    ),
)

PARTS = "\n".join(
    f"PART-{1000 + i}: bin {chr(65 + i % 6)}{i:02d}, {37 + i * 3} in stock, unit price {4.25 + i * 0.5:.2f}"
    for i in range(30)
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response(
        f"Here is today's parts list. Keep it for later.\n\n{PARTS}\n\nJust confirm you have it."
    )
    team.print_response("Thanks. What do you need from me to place an order?")
    team.print_response("Understood. I will come back with quantities.")

    result = team.compact(session_id=session_id)
    print(f"\n[{result.status.value}] {result.message}")

    run = team.run("Which bin is PART-1017 in, and how many are in stock?")
    print(f"\nAnswer: {run.content}")
    for tool in run.tools or []:
        if tool.tool_name == "search_compacted_history":
            print(f"Searched the archive for: {tool.tool_args}")
