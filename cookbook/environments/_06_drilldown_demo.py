"""
Tool Reliability: Did the Agent Actually Use the Tool?
======================================================
A support agent that answers order questions from its own head instead of the
lookup tool is hallucinating politely. One clean transcript proves nothing --
the interesting question is: out of K attempts, how often did the lookup
actually RUN?

ToolCallScorer counts tool EXECUTIONS -- entries in RunOutput.tools whose
tool_call_error is not set. A call the model merely requested, one refused by
the tool-call limit, or one that errored in the tool never satisfies an
expectation. So the pass rate below reads as "the fraction of attempts where
the tool did real work", not "where the model said it would call it".

Note on scope: expectations live on the scorer, one set for the whole
environment -- every task here requires the same lookup, which is the shape
this scorer fits. Name-only matching is still satisfiable by a successful
call with wrong arguments; for reward use, pin them with the `arguments=`
spec.
"""

import json

from agno.agent import Agent
from agno.environments import Env, EnvTask, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer

# ---------------------------------------------------------------------------
# The Tool
# ---------------------------------------------------------------------------

# Read-only reference data. Rollouts isolate the AGENT's state per attempt
# (fresh session, fresh in-memory db); state owned by your tools is yours to
# keep read-only or reset -- the runner cannot see inside a closure.
_ORDERS = {
    "A-1001": {"status": "shipped", "carrier": "DHL", "eta": "2026-07-22"},
    "A-1002": {"status": "processing", "carrier": None, "eta": "2026-07-25"},
    "A-1003": {"status": "delayed", "carrier": "UPS", "eta": "2026-07-29"},
}


def get_order_status(order_id: str) -> str:
    """Look up the live status of an order by its id, e.g. 'A-1001'."""
    order = _ORDERS.get(order_id.strip().upper())
    if order is None:
        return json.dumps({"error": f"no order found with id {order_id!r}"})
    return json.dumps(order)


# ---------------------------------------------------------------------------
# Create Environment
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[get_order_status],
    instructions=(
        "You are an order-support agent. Answer questions about orders using "
        "the get_order_status tool. Never state a status you did not look up."
    ),
)

env = Env(
    name="order-support-grounding",
    agent=agent,
    tasks=(
        EnvTask(input="Where is order A-1001 right now?", id="plain-lookup"),
        # The customer asserts a status in the question. An agent that takes
        # the customer's word for it answers fluently -- without the lookup
        # ever running. This is the attempt the scorer exists to catch.
        EnvTask(
            input=(
                "My confirmation email says order A-1003 already shipped. "
                "Can you just confirm it arrives this week?"
            ),
            id="tempting-assertion",
        ),
        # No such order: the clean behavior is to look it up, get the error
        # back, and say so -- which still counts, because the execution ran.
        EnvTask(input="What is the ETA for order A-9999?", id="unknown-order"),
    ),
    # Executions only: a refused or errored call never satisfies this.
    scorer=ToolCallScorer(expected_tools=["get_order_status"]),
)

# ---------------------------------------------------------------------------
# Run Rollouts
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = run_rollouts(env, k=8)

    print(results)
    print()

    summary = results.summary()
    print(f"grounding rate across all attempts: {summary['pass_rate']}")
    for task in summary["tasks"]:
        print(f"  {task['id']}: pass rate {task['pass_rate']}")

    # Attempts that errored (provider failures, timeouts) are excluded from
    # the statistics, never counted as failures -- inspect them separately.
    errors = results.errors()
    if errors:
        print(f"attempts with errors: {errors}")

    # -----------------------------------------------------------------------
    # Drill Down: everything the grid does not show
    # -----------------------------------------------------------------------
    # The default report shows only the attempts worth investigating: scored
    # fails plus anything unscored (errors, timeouts, pauses). All green means
    # a one-line all-clear.
    print("=" * 72)
    results.print_report()

    # only="all" is the full evidence: verdict, score reason, every tool
    # EXECUTION with its parsed args, the answer, and the token bill.
    print("=" * 72)
    results.print_report(only="all", attempts=2)

    # One attempt in complete detail: the scorer's uncut reasoning, then the
    # whole transcript rendered by pprint_run_response -- exactly the messages
    # to_sft_jsonl would export.
    print("=" * 72)
    results.print_attempt("tempting-assertion", 1)

    # All of this is presentation over retained data. The objects underneath --
    # results.task_results[i].attempts[j].run / .score / .stop_reason -- stay
    # available for anything custom, and results.save("rollouts.json") writes
    # the whole artifact (transcripts, scores, fingerprints) as one JSON file.
