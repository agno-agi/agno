"""
Reading the Evidence
====================
The grid gives you numbers; this file is about what to do when a number needs
investigating. Same environment as _03_tool_reliability.py -- an order-support
agent that must answer from its lookup tool -- but the point here is the
drill-down: errors(), print_report(), and print_attempt().

The report shows, per attempt, the verdict, the score's reason, every tool
EXECUTION with its parsed arguments, the answer, and the token bill. One
attempt can then be rendered in full: the scorer's uncut reasoning plus the
whole transcript -- exactly the messages to_sft_jsonl would export.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
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

env = Environment(
    name="order-support-grounding",
    agent=agent,
    tasks=(
        Task(input="Where is order A-1001 right now?", id="plain-lookup"),
        # The customer asserts a status in the question. An agent that takes
        # the customer's word for it answers fluently -- without the lookup
        # ever running. This is the attempt the scorer exists to catch.
        Task(
            input=(
                "My confirmation email says order A-1003 already shipped. "
                "Can you just confirm it arrives this week?"
            ),
            id="tempting-assertion",
        ),
        # No such order: the clean behavior is to look it up, get the error
        # back, and say so -- which still counts, because the execution ran.
        Task(input="What is the ETA for order A-9999?", id="unknown-order"),
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

    # -----------------------------------------------------------------------
    # Where this goes next
    # -----------------------------------------------------------------------
    # Everything above is verification and dataset generation: run K times,
    # score every attempt, read the evidence, export what passed
    # (_02_export_sft.py) for supervised fine-tuning. Nothing talks back to
    # the agent mid-run. The next step -- not in this release -- is the live
    # loop: an environment that responds to each agent turn and scores during
    # the interaction, so the scores can drive training directly.
