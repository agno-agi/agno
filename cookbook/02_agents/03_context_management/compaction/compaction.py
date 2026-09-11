"""
Compaction
=============================

Keeps a long session inside the context window. Once the conversation crosses a
threshold, the older messages are replaced by a generated summary and the recent
turns are kept verbatim.

`compaction=True` is the whole setup. Note that only the messages sent to the
model are shortened - the session still stores every message, which the run at
the bottom demonstrates.

Compaction triggers automatically at `compact_at_tokens` (150k by default), which a short
demo never reaches. So this example calls `agent.compact()` directly - the same fold the
automatic path performs, at a moment of your choosing.
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
    session_id="compaction_demo",
    add_history_to_context=True,
    # `compaction=True` would use the defaults. keep_last_runs is lowered so the fold
    # below has history in front of the tail to work with at demo scale.
    compaction=Compaction(keep_last_runs=2),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    questions = [
        "I am planning a trip to Japan in April. Remember that my budget is 4000 dollars.",
        "What are the best cities to see cherry blossoms?",
        "How many days should I spend in Kyoto?",
        "What is a reasonable daily food budget there?",
        "Do I need a rail pass?",
        "What about getting a pocket wifi?",
        "Which airport should I fly into?",
    ]

    for question in questions:
        agent.print_response(question)

    # Fold now, rather than waiting for the context to reach compact_at_tokens.
    # Returns a CompactionResult: `compacted` says whether a fold happened, and
    # `message` explains the outcome either way - declining is a normal answer,
    # since a summary cannot pay for itself on a short span.
    result = agent.compact(session_id="compaction_demo")
    if result.compacted:
        r = result.record
        print(
            f"\n[compacted {r.messages_compacted} messages: "
            f"{r.tokens_before} -> {r.tokens_after} tokens, archived={r.archived}]"
        )
    else:
        # Not an error: a summary cannot pay for itself on a short span, so the
        # server declines and says why.
        print(f"\n[{result.status.value}] {result.message}")

    # The next run sends the summary in place of the folded turns.
    agent.print_response("Remind me what my budget was.")

    # The summary shortens the request, never the record: every message the
    # session stored is still there.
    session = agent.get_session(session_id="compaction_demo")
    stored = sum(len(run.messages or []) for run in session.runs or [])
    print(f"\nMessages still stored in the session: {stored}")
