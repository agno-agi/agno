"""
CI Gating - Per-task floor
==========================

Protect every task instead of allowing strong rows to hide a weak one in the
aggregate. Normal runs print the decision; --enforce maps FAIL to exit status 1.
"""

import argparse

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class FinalInteger(BaseModel):
    value: int = Field(description="The final recurrence value")


def exact_integer(run, expected) -> bool:
    return isinstance(run.content, FinalInteger) and run.content.value == expected


agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.5",
        reasoning_effort="low",
        verbosity="low",
        max_output_tokens=3000,
    ),
    instructions="Compute the recurrence exactly and return only the final integer.",
    output_schema=FinalInteger,
)

env = Environment(
    name="ci-per-task-floor",
    agent=agent,
    tasks=(
        Task(id="easy-anchor", input="Multiply 17 by 23.", expected=391),
        Task(
            id="rounds-eight",
            input=(
                "Let a0=271828. For n=1 through 8, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_8."
            ),
            expected=6856135,
        ),
        Task(
            id="rounds-ten",
            input=(
                "Let a0=271828. For n=1 through 10, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_10."
            ),
            expected=542370,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the per-task environment CI gate."
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="exit with status 1 when the gate decision is FAIL",
    )
    parser.add_argument(
        "--minimum-task-rate",
        type=float,
        default=0.50,
        help="per-task pass-rate floor from 0.0 through 1.0",
    )
    args = parser.parse_args()
    if not 0 <= args.minimum_task_rate <= 1:
        parser.error("--minimum-task-rate must be between 0.0 and 1.0")
    return args


if __name__ == "__main__":
    args = parse_args()
    result = run_rollouts(env, k=4, concurrency=4)
    print(result)

    minimum_task_rate = args.minimum_task_rate
    task_rows = result.summary()["tasks"]
    violations = [
        row["id"]
        for row in task_rows
        if row["pass_rate"] is None
        or row["pass_rate"] < minimum_task_rate
        or row["n_unscored"] > 0
    ]
    decision = "PASS" if not violations else "FAIL"
    print(f"gate decision: {decision}")
    print(f"minimum task pass rate: {minimum_task_rate}")
    print(f"violations: {violations}")
    if args.enforce and violations:
        print("enforcement enabled: exiting with status 1")
        raise SystemExit(1)
    print(f"enforcement enabled: {args.enforce}")
