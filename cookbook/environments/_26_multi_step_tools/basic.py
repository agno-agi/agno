"""
Multi-step Tools - Basic
========================

Require a dispatch-plan read followed by a current hub-window lookup. A routing
checksum decides whether the copied cutoff is trustworthy, making skipped
second steps visible across repeated attempts.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer

_PLANS = {
    "S-104": {"hub_code": "H-17", "cached_cutoff": "17:00"},
    "S-105": {"hub_code": "H-19", "cached_cutoff": "16:40"},
}


def read_dispatch_plan(shipment_id: str) -> str:
    """Read the current dispatch plan for a shipment id."""
    return json.dumps(_PLANS.get(shipment_id, {"error": "shipment not found"}))


def lookup_hub_window(hub_code: str) -> str:
    """Read the current dispatch cutoff for a hub code."""
    windows = {"H-17": "17:22", "H-19": "16:55"}
    return json.dumps({"hub_code": hub_code, "cutoff": windows.get(hub_code)})


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[read_dispatch_plan, lookup_hub_window],
    instructions=(
        "Resolve dispatch questions from read-only records. Read the plan first. "
        "When the task's routing rule says the cached cutoff is stale, also look up "
        "the current hub window before answering."
    ),
)

env = Environment(
    name="multi-step-tool-names",
    agent=agent,
    tasks=(
        Task(
            id="direct-two-step",
            input=(
                "For shipment S-104, read its dispatch plan and then verify the current "
                "window for the plan's hub. Can it leave if ready at 17:10?"
            ),
        ),
        Task(
            id="checksum-eight",
            input=(
                "Check shipment S-104. Let a0=271828. For n=1 through 8, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. If a_8 is odd, the "
                "plan's cached cutoff is stale and you must look up the hub window; "
                "if even, use the cached cutoff."
            ),
        ),
        Task(
            id="checksum-nine",
            input=(
                "Check shipment S-104. Let a0=271828. For n=1 through 9, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. If a_9 is even, the "
                "plan's cached cutoff is stale and you must look up the hub window; "
                "if odd, use the cached cutoff."
            ),
        ),
    ),
    scorer=ToolCallScorer(expected_tools=["read_dispatch_plan", "lookup_hub_window"]),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=6, concurrency=6)
    print(result)
    for task_result in result.task_results:
        print(
            f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored} "
            "completed both lookups"
        )
