"""
CI Gating - Basic
=================

Read the stable summary mapping and print an aggregate gate decision. Normal
runs remain successful for inspection; --enforce maps FAIL to exit status 1.
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
    name="ci-gate-basic",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the aggregate environment CI gate."
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="exit with status 1 when the gate decision is FAIL",
    )
    parser.add_argument(
        "--minimum-pass-rate",
        type=float,
        default=0.60,
        help="aggregate pass-rate floor from 0.0 through 1.0",
    )
    args = parser.parse_args()
    if not 0 <= args.minimum_pass_rate <= 1:
        parser.error("--minimum-pass-rate must be between 0.0 and 1.0")
    return args


if __name__ == "__main__":
    args = parse_args()
    result = run_rollouts(env, k=4, concurrency=4)
    print(result)

    summary = result.summary()
    minimum_pass_rate = args.minimum_pass_rate
    pass_rate = summary["pass_rate"]
    gate_passed = (
        pass_rate is not None
        and pass_rate >= minimum_pass_rate
        and summary["n_unscored"] == 0
    )
    decision = "PASS" if gate_passed else "FAIL"
    print(f"gate decision: {decision}")
    print(f"observed pass rate: {pass_rate}; required: {minimum_pass_rate}")
    print(f"unscored attempts: {summary['n_unscored']}")
    if args.enforce and not gate_passed:
        print("enforcement enabled: exiting with status 1")
        raise SystemExit(1)
    print(f"enforcement enabled: {args.enforce}")
