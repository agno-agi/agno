"""
Tool-call scorer - Basic
========================

Run operational questions repeatedly and verify that the agent grounded its
answer with a real tool execution. Difficult routing arithmetic makes required
lookups inconsistent without making an unnecessary lookup count as success.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer

_CUTOFFS = {"north": "17:00", "south": "16:30"}


def lookup_shipping_cutoff(region: str) -> str:
    """Return today's official dispatch cutoff for a lower-case region slug."""
    return json.dumps({"region": region, "cutoff": _CUTOFFS.get(region)})


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[lookup_shipping_cutoff],
    instructions=(
        "You plan same-day dispatch. Follow each routing rule exactly. When it says "
        "to look up the cutoff, call lookup_shipping_cutoff with a lower-case region. "
        "When it says not to look it up, answer without calling the tool."
    ),
)

env = Environment(
    name="tool-name-matching",
    agent=agent,
    tasks=(
        Task(
            id="direct-lookup",
            input=(
                "Look up today's official North cutoff before deciding whether a "
                "parcel arriving at 16:45 can ship today."
            ),
        ),
        Task(
            id="checksum-route-a",
            input=(
                "Multiply 2718281828459045 by 1618033988749895. Add every decimal "
                "digit of the product, multiply that sum by 131071, then subtract the "
                "product remainder modulo 65521. If the final integer is odd, look up "
                "today's North cutoff; if it is even, do not call any tool."
            ),
        ),
        Task(
            id="checksum-route-b",
            input=(
                "Multiply 3141592653589793 by 1414213562373095. Add every decimal "
                "digit of the product, multiply that sum by 65537, then subtract the "
                "product remainder modulo 32749. If the final integer is odd, look up "
                "today's South cutoff; if it is even, do not call any tool."
            ),
        ),
    ),
    scorer=ToolCallScorer(expected_tools=["lookup_shipping_cutoff"]),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=6, concurrency=6)
    print(result)
    for task_result in result.task_results:
        print(
            f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored} "
            "executed the lookup"
        )
