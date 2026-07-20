"""
Support Triage — the learning zone at a glance
==============================================
Classify real support tickets, run each many times, and watch the grid split
into tasks the agent nails, tasks it is shaky on, and tasks it never gets.

The middle band is the whole point. A task the agent always passes teaches a
trainer nothing (no signal); a task it always fails teaches nothing either.
The tasks where it *sometimes* wins -- 0 < pass rate < 1 -- are the learning
zone, and `results.learning_zone()` hands you exactly those, ready to export.

Run it a second time after a prompt or model change and the grid tells you what
moved. This is the tweet screenshot: one run, the pass rate per task, the
learning zone called out.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts, to_sft_jsonl
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# The agent: classify a ticket into one bucket. Structured output so the
# verifier compares a typed field, never a free-text string.
# ---------------------------------------------------------------------------

BUCKETS = ("billing", "bug", "feature_request", "account_access")


class Triage(BaseModel):
    category: str
    reason: str


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    output_schema=Triage,
    instructions=(
        "You triage support tickets. Classify each into exactly one of: "
        f"{', '.join(BUCKETS)}. Pick the single best fit."
    ),
)

# ---------------------------------------------------------------------------
# The task set: a clean case per bucket, plus two deliberately ambiguous ones
# (a crash *during payment*, a charge dispute that reads like a bug) that a
# good model gets right most-but-not-all of the time -- the learning zone.
# ---------------------------------------------------------------------------

env = Environment(
    name="support-ticket-triage",
    agent=agent,
    tasks=(
        Task(
            id="double-charge",
            input="I was charged twice for my July invoice. Refund one.",
            expected="billing",
        ),
        Task(
            id="export-bug",
            input="The export button does nothing; the console shows a TypeError.",
            expected="bug",
        ),
        Task(
            id="dark-mode",
            input="Please add a dark mode -- half my team works nights.",
            expected="feature_request",
        ),
        Task(
            id="locked-out",
            input="Can't log in since this morning and the reset email never arrives.",
            expected="account_access",
        ),
        Task(
            id="crash-charge",
            input="The app crashed mid-payment and now I see two pending charges.",
            expected="billing",
        ),
        Task(
            id="slow-then-refund",
            input="Reports take 30s to load and I want a refund for the trouble.",
            expected="billing",
        ),
    ),
    # Compare the typed field, not a string: cookbook _01 shows why this matters.
    scorer=CodeScorer(lambda run, expected: run.content.category == expected),
)

if __name__ == "__main__":
    # k=8 attempts per task, 4 in flight. The grid renders live on a TTY and
    # prints statically here; summary() is the machine-readable contract.
    results = run_rollouts(env, k=8, concurrency=4)
    print(results)

    zone = results.learning_zone()
    print("\nlearning zone (tasks worth training on):")
    for task_result in zone.task_results:
        print(f"  - {task_result.task.id}: {task_result.pass_rate:.2f}")

    # Keep only the passing attempts on the learnable tasks -- a supervised
    # fine-tuning file, no extra labelling.
    report = to_sft_jsonl(zone, "data/generated/triage_sft.jsonl")
    print(
        f"\nexported {report.n_written} passing trajectories -> data/generated/triage_sft.jsonl"
    )
