"""
Tool-call scorer - Match arguments
==================================

Name-only scoring cannot tell whether an agent queried the right record. Add an
argument subset when the region, service, and effective date are part of the
behavior being verified.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer


def quote_shipping_cutoff(
    region: str, service: str, effective_date: str = "latest"
) -> str:
    """Quote a cutoff using lower-case slugs and either YYYY-MM-DD or 'latest'."""
    return json.dumps(
        {
            "region": region,
            "service": service,
            "effective_date": effective_date,
            "cutoff": "17:00",
        }
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[quote_shipping_cutoff],
    instructions=(
        "Verify shipping cutoffs with the tool. Use lower-case slugs. Some audits use "
        "a checksum to disambiguate duplicate records; calculate it exactly before "
        "choosing the tool arguments."
    ),
)

env = Environment(
    name="tool-argument-matching",
    agent=agent,
    tasks=(
        Task(
            id="checksum-date",
            input=(
                "Two North priority records are candidates. Multiply 2718281828459045 "
                "by 1618033988749895; add the product's decimal digits; multiply that "
                "sum by 131071; subtract the product remainder modulo 65521. If the "
                "final routing code is odd, quote 2026-07-20; if even, quote 2026-07-21."
            ),
        ),
        Task(
            id="checksum-service",
            input=(
                "For North on 2026-07-20, multiply 3141592653589793 by "
                "1414213562373095 and add the decimal digits of the product. If that "
                "sum is divisible by 5, quote priority; otherwise quote express."
            ),
        ),
        Task(
            id="checksum-region",
            input=(
                "For priority on 2026-07-20, multiply 2718281828459045 by "
                "1618033988749895 and find the product remainder modulo 65521. Quote "
                "North if it is below 30000; otherwise quote North-East."
            ),
        ),
    ),
    scorer=ToolCallScorer(
        expected_tools=["quote_shipping_cutoff"],
        arguments={
            "quote_shipping_cutoff": {
                "region": "north",
                "service": "priority",
                "effective_date": "2026-07-20",
            }
        },
    ),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=6, concurrency=6)
    print(result)
    for task_result in result.task_results:
        print(
            f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored} "
            "matched the required arguments"
        )
