"""
Team Compaction
=============================

Keeps a long conversation with a Team inside the context window. What is compacted
is the team leader's conversation: the person's messages, the leader's answers and
its delegations, each with the member's answer as its result. Older messages are
replaced by a generated summary and the recent turns are kept verbatim. The session
still stores every message, which the run at the bottom demonstrates.

`compaction=True` folds when the provider rejects a request as too long, and not
before. Pass a `Compaction` object to fold at a size you choose:

    compaction=Compaction(compact_at_tokens=100_000)

With a threshold, the leader is sent every turn since the last fold, not only the
last `num_history_runs`: the threshold is the limit.

The size is checked when a run starts. A run that grows past it through many
delegations is folded only if the provider rejects a request.

Either way `team.compact()` folds on demand, which is what this example uses: a
short demo reaches neither the provider's limit nor a threshold.
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
planner = Agent(
    name="Trip Planner",
    role="Plans routes, days per city and transport",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)
budgeter = Agent(
    name="Budget Analyst",
    role="Estimates costs and keeps the trip inside the budget",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Travel Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[planner, budgeter],
    db=db,
    session_id="team_compaction_demo",
    add_history_to_context=True,
    # `compaction=True` would fold only on a provider rejection. uncompacted_runs is lowered so the
    # fold below has history in front of the tail to work with at demo scale.
    compaction=Compaction(uncompacted_runs=2),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    questions = [
        "I am planning a trip to Japan in April. Remember that my budget is 4000 dollars.",
        "Which cities are best for cherry blossoms?",
        "How many days should I spend in Kyoto?",
        "What is a reasonable daily food budget there?",
        "Do I need a rail pass?",
        "Which airport should I fly into?",
    ]

    for question in questions:
        team.print_response(question)

    # Fold now, rather than waiting for the context to reach compact_at_tokens.
    # Returns a CompactionResult: `compacted` says whether a fold happened, and
    # `message` explains the outcome either way.
    result = team.compact(session_id="team_compaction_demo")
    if result.compacted:
        r = result.record
        print(
            f"\n[compacted {r.messages_compacted} messages: "
            f"{r.tokens_before} -> {r.tokens_after} tokens, archived={r.archived}]"
        )
    else:
        print(f"\n[{result.status.value}] {result.message}")

    # The next run sends the leader the summary in place of the folded turns.
    team.print_response("Remind me what my budget was.")

    # The summary shortens the request, never the record: every message the
    # session stored is still there, the leader's and the members'.
    session = team.get_session(session_id="team_compaction_demo")
    stored = sum(len(run.messages or []) for run in session.runs or [])
    print(f"\nMessages still stored in the session: {stored}")
