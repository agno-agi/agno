"""
CI Gating - Baseline regression
===============================

Save and reload a baseline, run a candidate policy, and gate on task-level
pass-rate drops from `EnvironmentDiff`. Normal runs print the decision;
--enforce maps FAIL to exit status 1.
"""

import argparse
from pathlib import Path

from agno.agent import Agent
from agno.environments import (
    Environment,
    EnvironmentDiff,
    EnvironmentRunResult,
    Task,
    run_rollouts,
)
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
        reasoning_effort="high",
        verbosity="low",
        max_output_tokens=6000,
    ),
    instructions="Compute the recurrence exactly and return only the final integer.",
    output_schema=FinalInteger,
)

env = Environment(
    name="ci-baseline-regression",
    agent=agent,
    tasks=(
        Task(
            id="rounds-eight",
            input=(
                "Let a0=271828. For n=1 through 8, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_8."
            ),
            expected=6856135,
        ),
        Task(
            id="rounds-nine",
            input=(
                "Let a0=271828. For n=1 through 9, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. Return a_9."
            ),
            expected=7826798,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)

baseline_path = Path(__file__).parent / "data" / "generated" / "ci_baseline.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the baseline regression CI gate.")
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="exit with status 1 when the gate decision is FAIL",
    )
    parser.add_argument(
        "--maximum-drop",
        type=float,
        default=0.25,
        help="largest allowed per-task pass-rate drop from 0.0 through 1.0",
    )
    args = parser.parse_args()
    if not 0 <= args.maximum_drop <= 1:
        parser.error("--maximum-drop must be between 0.0 and 1.0")
    return args


if __name__ == "__main__":
    args = parse_args()
    baseline = run_rollouts(env, k=4, concurrency=4)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline.save(baseline_path)
    loaded_baseline = EnvironmentRunResult.load(baseline_path)

    current = run_rollouts(
        env,
        k=4,
        concurrency=4,
        model=OpenAIResponses(
            id="gpt-5.5",
            reasoning_effort="low",
            verbosity="low",
            max_output_tokens=6000,
        ),
    )
    print("Baseline")
    print(loaded_baseline)
    print("Current")
    print(current)

    diff: EnvironmentDiff = current.diff(loaded_baseline)
    print(diff)
    maximum_drop = args.maximum_drop
    violations = [
        row["id"]
        for row in diff.rows
        if row["delta"] is None or row["delta"] < -maximum_drop
    ]
    baseline_unscored = loaded_baseline.n_unscored
    current_unscored = current.n_unscored
    gate_passed = (
        not violations
        and not diff.unmatched_current
        and not diff.unmatched_baseline
        and baseline_unscored == 0
        and current_unscored == 0
    )
    decision = "PASS" if gate_passed else "FAIL"
    print(f"gate decision: {decision}")
    print(f"maximum allowed task drop: {maximum_drop}")
    print(f"regression violations: {violations}")
    print(f"baseline unscored attempts: {baseline_unscored}")
    print(f"current unscored attempts: {current_unscored}")
    if args.enforce and not gate_passed:
        print("enforcement enabled: exiting with status 1")
        raise SystemExit(1)
    print(f"enforcement enabled: {args.enforce}")
