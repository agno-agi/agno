"""
Compaction With Thinking And Tools
=============================

Extended thinking plus tool calls is the hardest shape for compaction, because
an assistant turn is then three things at once: a thinking block, a tool call,
and the result that answers it. All three have to stay together.

How each provider carries thinking decides how much can go wrong:

- Anthropic keeps the thinking block *in the message*, as reasoning_content
  with a signature. Compaction copies messages without touching those fields, so
  a kept turn arrives intact and a folded one takes its thinking with it.

- OpenAI's Responses API keeps reasoning items *on the server*, reachable by
  previous_response_id. Compaction severs that chain on purpose - otherwise the
  server replays the history the fold just removed - so the reasoning item has
  to travel in the request instead, or the API rejects the function_call it
  belongs to.

Either way the rule is the same: a tool batch is never split by the cut.

Prerequisites: ANTHROPIC_API_KEY, and a Postgres running on localhost:5532
Run: .venvs/demo/bin/python cookbook/02_agents/03_context_management/compaction/compaction_anthropic_thinking.py
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
compaction = Compaction(compact_at_runs=4, keep_last_runs=1)

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-5", thinking={"type": "enabled", "budget_tokens": 1024}
    ),
    db=db,
    session_id="compaction_anthropic_thinking",
    tools=[CalculatorTools()],
    add_history_to_context=True,
    num_history_runs=100,
    compaction=compaction,
    instructions=[
        "Use the calculator for arithmetic rather than doing it in your head.",
        "Then answer at length - long answers grow the context, which is the point here.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for question in [
        "Compute 8123 * 4471, then explain multiplication algorithms in detail.",
        "Compute 99991 / 7, then explain long division and remainders in detail.",
        "Compute the factorial of 12, then explain combinatorial growth in detail.",
        "Compute 2**40, then explain binary growth and storage sizes in detail.",
        "Which result so far was the largest, and why?",
    ]:
        agent.print_response(question)
        run = agent.get_last_run_output(session_id="compaction_anthropic_thinking")
        if run is not None and run.compaction is not None:
            r = run.compaction
            print(
                f"\n[compacted {r.messages_compacted} messages: {r.tokens_before} -> {r.tokens_after} tokens]"
            )

    session = agent.get_session(session_id="compaction_anthropic_thinking")
    messages = [m for run in (session.runs or []) for m in (run.messages or [])]
    thinking = sum(1 for m in messages if m.reasoning_content)
    print(f"\nStored messages: {len(messages)} | with thinking: {thinking}")
    print(f"Compactions: {compaction.stats.compactions}")
