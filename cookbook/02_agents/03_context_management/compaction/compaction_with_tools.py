"""
Compaction With Tools
=============================

A tool call is stored as three messages, not one:

    assistant   tool_calls=[{id: call_1, ...}]   the request
    tool        tool_call_id=call_1              the result - usually the bulk
    assistant   "the answer"                     what the model made of it

Compaction has to respect that grouping. The cut never lands between an
assistant's tool_calls and the tool message answering it: providers reject a
function_call whose result is missing, so a boundary that would split a batch is
moved to keep the batch whole.

Tool results are also the bulkiest part of a transcript and the least useful to
carry verbatim, so they get a cheaper treatment than a summary: results older
than the elision watermark render as a short placeholder in the request, while
the full text stays in the transcript and the archive.

Prerequisites: OPENAI_API_KEY, and a Postgres running on localhost:5532
Run: .venvs/demo/bin/python cookbook/02_agents/03_context_management/compaction/compaction_with_tools.py
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
compaction = Compaction(
    compact_at_runs=4,
    keep_last_runs=1,
    # On by default. Old tool results become "[tool result elided: N chars]" in
    # the request - no summarizer call, and often more reclaimed than the fold.
    elide_tool_results=True,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    session_id="compaction_with_tools",
    tools=[CalculatorTools()],
    add_history_to_context=True,
    num_history_runs=100,
    compaction=compaction,
    instructions=[
        "Use the calculator for arithmetic rather than doing it in your head."
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for question in [
        "Compute 8123 * 4471 and explain what the magnitude means.",
        "Now compute 99991 / 7 and explain long division.",
        "Compute the factorial of 12 and explain why factorials grow so fast.",
        "Compute 2**40 and explain binary growth.",
        "Which of the results so far was the largest?",
    ]:
        agent.print_response(question)
        run = agent.get_last_run_output(session_id="compaction_with_tools")
        if run is not None and run.compaction is not None:
            r = run.compaction
            print(
                f"\n[compacted {r.messages_compacted} messages: {r.tokens_before} -> {r.tokens_after} tokens]"
            )

    # Every tool call and result is still stored, however much the request shrank.
    session = agent.get_session(session_id="compaction_with_tools")
    messages = [m for run in (session.runs or []) for m in (run.messages or [])]
    print(f"\nStored messages: {len(messages)}")
    print(
        f"  assistant turns with tool calls: {sum(1 for m in messages if m.tool_calls)}"
    )
    print(f"  tool results: {sum(1 for m in messages if m.role == 'tool')}")
