"""
Tool-call scorer - Strict tools
===============================

Require the grounding lookup and reject clean executions of unexpected tool
names. The time arithmetic sits near the boundary where the model may calculate
mentally or call an unnecessary second tool.
"""

import json
from datetime import datetime

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer


def lookup_shipping_cutoff(region: str) -> str:
    """Return today's official dispatch cutoff for a region."""
    return json.dumps({"region": region, "cutoff": "17:22"})


def minutes_between(start: str, end: str) -> int:
    """Return elapsed minutes between two HH:MM times on the same day."""
    start_time = datetime.strptime(start, "%H:%M")
    end_time = datetime.strptime(end, "%H:%M")
    return int((end_time - start_time).total_seconds() // 60)


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[lookup_shipping_cutoff, minutes_between],
    instructions=(
        "Always look up the current cutoff. You may do time arithmetic mentally; "
        "follow any audit routing rule exactly before deciding whether to use "
        "minutes_between."
    ),
)

env = Environment(
    name="strict-tool-matching",
    agent=agent,
    tasks=(
        Task(
            id="lean-anchor",
            input=(
                "Look up the West cutoff, then tell me exactly how many minutes remain "
                "from 17:00. Use only the lookup and do the subtraction yourself."
            ),
        ),
        Task(
            id="checksum-route-a",
            input=(
                "Look up the West cutoff and report minutes remaining from 16:37. To "
                "route tool use, multiply 2718281828459045 by 1618033988749895; add "
                "the product's decimal digits; multiply by 131071; subtract the product "
                "remainder modulo 65521. If the result is odd, do the time subtraction "
                "yourself; if even, also call minutes_between."
            ),
        ),
        Task(
            id="checksum-route-b",
            input=(
                "Look up the West cutoff and report minutes remaining from 15:48. To "
                "route tool use, multiply 3141592653589793 by 1414213562373095; add "
                "the product's decimal digits; multiply by 65537; subtract the product "
                "remainder modulo 32749. If the result is odd, do the time subtraction "
                "yourself; if even, also call minutes_between."
            ),
        ),
    ),
    scorer=ToolCallScorer(
        expected_tools=["lookup_shipping_cutoff"],
        allow_additional=False,
    ),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=6, concurrency=6)
    print(result)
    for task_result in result.task_results:
        print(
            f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored} "
            "used no unexpected tool names"
        )
