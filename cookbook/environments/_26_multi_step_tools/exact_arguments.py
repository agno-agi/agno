"""
Multi-step Tools - Exact arguments
==================================

Two successful tool names are still insufficient if either step targets the
wrong record. Route between duplicate candidates, then match the exact shipment
and hub arguments recorded on the executions.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer


def read_dispatch_plan(shipment_id: str) -> str:
    """Read a dispatch plan for shipment S-104 or S-105."""
    plans = {
        "S-104": {"hub_code": "H-17", "service_date": "2026-07-20"},
        "S-105": {"hub_code": "H-19", "service_date": "2026-07-21"},
    }
    return json.dumps(plans.get(shipment_id, {"error": "shipment not found"}))


def lookup_hub_window(hub_code: str, service_date: str) -> str:
    """Read a hub cutoff for a hub code and ISO service date."""
    return json.dumps(
        {
            "hub_code": hub_code,
            "service_date": service_date,
            "cutoff": "17:22" if hub_code == "H-17" else "16:55",
        }
    )


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[read_dispatch_plan, lookup_hub_window],
    instructions=(
        "Use both read-only tools. Calculate any routing recurrence exactly, choose "
        "one candidate, read that plan, then query the hub and date returned by it."
    ),
)

env = Environment(
    name="multi-step-exact-arguments",
    agent=agent,
    tasks=(
        Task(
            id="route-by-eight",
            input=(
                "Duplicate scans map to S-104 and S-105. Let a0=271828. For n=1 "
                "through 8, set a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. "
                "If a_8 is odd, investigate S-104; otherwise investigate S-105. "
                "Read the chosen plan and its current hub window."
            ),
        ),
        Task(
            id="route-by-nine",
            input=(
                "Duplicate scans map to S-104 and S-105. Let a0=271828. For n=1 "
                "through 9, set a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. "
                "If a_9 is even, investigate S-104; otherwise investigate S-105. "
                "Read the chosen plan and its current hub window."
            ),
        ),
    ),
    scorer=ToolCallScorer(
        expected_tools=["read_dispatch_plan", "lookup_hub_window"],
        arguments={
            "read_dispatch_plan": {"shipment_id": "S-104"},
            "lookup_hub_window": {
                "hub_code": "H-17",
                "service_date": "2026-07-20",
            },
        },
    ),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=6, concurrency=6)
    print(result)
    for task_result in result.task_results:
        print(
            f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored} "
            "matched both records"
        )
