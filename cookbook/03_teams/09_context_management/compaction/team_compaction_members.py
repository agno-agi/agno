"""
Compaction For A Team Member
=============================

`Team(compaction=...)` compacts the team leader's conversation only. A member
that keeps its own history across delegations, with `add_history_to_context=True`,
is compacted by a `compaction` of its own.

A Team gives a member its earlier tasks and answers as input. When that history
reaches the member's `compact_at_tokens`, the Team folds it before it hands over
the next task: the member is given a summary and the turns kept after it. The
summary is written once and stored, then replayed on later delegations.

The leader and the member each keep their own folds in the shared session. Each
compaction record names its owner, and each reads only its own.

The size measured for a member is its history, without its system prompt, its
tools and the new task. The summary's usage is added to the team run that
delegates.
"""

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
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    id="researcher",
    role="Explains database topics in detail and remembers what it explained earlier",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    add_history_to_context=True,
    num_history_runs=20,
    # A low threshold so a short demo folds. The member's history is folded by this
    # setting, whatever the Team's own compaction is.
    compaction=Compaction(compact_at_tokens=2_000, uncompacted_runs=1),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Database Team",
    id="database-team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[researcher],
    db=db,
    session_id="team_compaction_members",
    add_history_to_context=True,
    instructions="Delegate every question to the Researcher. Answer in two sentences.",
    # The leader's own conversation, compacted separately from the member's.
    compaction=Compaction(compact_at_tokens=100_000),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    questions = [
        "Explain database indexing in detail, with worked examples.",
        "Explain B-tree indexes in depth and when they are the right choice.",
        "Explain hash indexes and how they differ, in detail.",
        "Explain covering indexes and index-only scans, in detail.",
        "Which of the index types you explained suits a range query best?",
    ]

    for question in questions:
        team.print_response(question)

    # Each record names whose conversation it folded: the member's id here.
    records = db.get_compactions_for_session("team_compaction_members")
    print(f"\nCompaction records in the session: {len(records)}")
    for record in reversed(records):
        print(
            f"  owner={record['owner_id']} folded {record['messages_compacted']} messages: "
            f"{record['tokens_before']} -> {record['tokens_after']} tokens"
        )
