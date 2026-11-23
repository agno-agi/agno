"""
Tool-call scorer - Basic
========================

Run operational questions repeatedly and verify two things at once: the agent
grounded its answer with the required lookup, and it slipped in no unnecessary
tool call. The routing arithmetic tempts an avoidable backup lookup, so a clean
run and a padded one are told apart by the executions, not by the prose. The
tasks are calibrated against gpt-5.5, where the temptation is followed
inconsistently -- that inconsistency is the learning zone.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer

_CUTOFFS = {"north": "17:00", "south": "16:30"}
_BACKUP_CARRIERS = {"north": "NorthEx", "south": "SouthLink"}


def lookup_shipping_cutoff(region: str) -> str:
    """Return today's official dispatch cutoff for a lower-case region slug."""
    return json.dumps({"region": region, "cutoff": _CUTOFFS.get(region)})


def lookup_backup_carrier(region: str) -> str:
    """Return the standby carrier, needed only when the primary carrier is down."""
    return json.dumps({"region": region, "backup": _BACKUP_CARRIERS.get(region)})


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[lookup_shipping_cutoff, lookup_backup_carrier],
    instructions=(
        "You plan same-day dispatch. Always call lookup_shipping_cutoff to ground the "
        "official cutoff before you decide. Call lookup_backup_carrier only when a "
        "routing rule establishes the primary carrier is down; when the rule leaves the "
        "primary carrier operating, a backup lookup is unnecessary. Do the routing "
        "arithmetic yourself."
    ),
)

env = Environment(
    name="tool-name-matching",
    agent=agent,
    tasks=(
        Task(
            id="direct-lookup",
            input=(
                "The primary carrier is operating normally. Look up today's official "
                "North cutoff, then say whether a parcel arriving at 16:45 can ship today."
            ),
        ),
        Task(
            id="checksum-route-a",
            input=(
                "Multiply 2718281828459045 by 1618033988749895. Add every decimal digit "
                "of the product, multiply that sum by 131071, then subtract the product "
                "remainder modulo 65521. If the final integer is even, the primary "
                "carrier is down, so also look up the North backup carrier; if it is odd, "
                "the primary carrier is fine. Either way, ground the North cutoff."
            ),
        ),
        Task(
            id="checksum-route-b",
            input=(
                "Multiply 3141592653589793 by 1414213562373095. Add every decimal digit "
                "of the product, multiply that sum by 65537, then subtract the product "
                "remainder modulo 32749. If the final integer is even, the primary "
                "carrier is down, so also look up the South backup carrier; if it is odd, "
                "the primary carrier is fine. Either way, ground the South cutoff."
            ),
        ),
    ),
    # Require the grounding lookup, and reject any run that also fired the backup
    # lookup: an unnecessary tool call is not a clean run.
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
            "grounded with no unnecessary call"
        )
