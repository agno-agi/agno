"""
Your First Environment
======================
Take an agent you already wrote, run it many times against a set of tasks,
and score every attempt automatically.

Agent output is sampled, so one run proves nothing. Running each task K times
and counting gives you a real pass RATE, and re-running after a prompt edit,
a tool change, or a model swap tells you what moved.

The grid renders live while the run is in flight (on a TTY), one glyph per
attempt; print(results) shows the same grid statically, and results.summary()
is the machine-readable contract for CI.

See also: _02_export_sft.py for turning the runs that worked into a
supervised fine-tuning dataset.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Create Environment
# ---------------------------------------------------------------------------


class Answer(BaseModel):
    value: int
    reasoning: str


def exact(run, expected):
    # The verifier compares a typed field, not a string. String comparison against
    # structured output is where most first environments quietly go wrong.
    return run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"), output_schema=Answer
)

env = Environment(
    name="mental-math",
    agent=agent,
    tasks=(
        # Easy: expect 8/8, carries no signal.
        Task(input="What is 17 x 23?", expected=391),
        # Hard enough that attempts disagree: a long chained computation on
        # sixteen-digit factors gives sampling several chances to slip, where
        # single products saturate at 8/8.
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. Add the "
                "decimal digits of the product, multiply that digit sum by 131071, "
                "then subtract the product's remainder modulo 65521."
            ),
            expected=20944939,
        ),
    ),
    # A named function, so the environment fingerprints cleanly: edit the function
    # and env_fingerprint flips, telling you the environment drifted.
    scorer=CodeScorer(exact),
)

# ---------------------------------------------------------------------------
# Run Rollouts
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Eight isolated attempts per task: fresh session, fresh in-memory db, no memory
    # capture, response cache off. A pass rate you can trust.
    results = run_rollouts(env, k=8)

    print(results)
    print()

    summary = results.summary()
    print(f"pass rate: {summary['pass_rate']}")
    print(f"scored attempts: {summary['n_scored']} of {summary['n_attempts']}")
    print(f"env fingerprint: {summary['env_fingerprint']}")
    print(f"policy fingerprint: {summary['policy_fingerprint']}")

    # The tasks whose attempts disagreed are the ones carrying signal.
    zone_ids = [task["id"] for task in summary["tasks"] if task["learning_zone"]]
    print(f"learning zone tasks: {zone_ids}")
