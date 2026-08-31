"""
Compaction
=============================

Keeps a long session inside the context window. Once the conversation crosses a
threshold, the older messages are replaced by a generated summary and the recent
turns are kept verbatim.

`compaction=True` is the whole setup. Note that only the messages sent to the
model are shortened - the session still stores every message, which the run at
the bottom demonstrates.

The defaults (compact at 20 runs, keep the last 5) suit a long-lived session.
This example lowers them so a short demo actually triggers a compaction.
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction.db"),
    session_id="compaction_demo",
    add_history_to_context=True,
    # Without a window, history is capped at 3 runs and compaction never sees
    # enough of the conversation to be worth doing.
    num_history_runs=100,
    # `compaction=True` uses the defaults; these are lowered to fit the demo.
    compaction=Compaction(compact_at_runs=5, keep_last_runs=2),
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
        "Remind me what my budget was.",
    ]

    for question in questions:
        print(f"\n--- {question}")
        run = agent.run(question)
        print(run.content)

        # `run.compaction` reports what compaction did on this run, if anything.
        if run.compaction is not None:
            r = run.compaction
            print(
                f"\n[compacted {r.messages_compacted} messages at boundary {r.boundary}: "
                f"{r.tokens_before} -> {r.tokens_after} tokens, archived at {r.archive_path}]"
            )

    # The summary shortens the request, never the record: every message the
    # session stored is still there.
    session = agent.get_session(session_id="compaction_demo")
    stored = sum(len(run.messages or []) for run in session.runs or [])
    print(f"\nMessages still stored in the session: {stored}")
