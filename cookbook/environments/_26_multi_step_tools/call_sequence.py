"""
Multi-step Tools - Call sequence
================================

Score a three-step dependency chain in execution order and against the records
selected by a routing checksum. Only plan, window, then weather preserves the
evidence chain; copied hints must not replace values returned by earlier steps.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer


def read_dispatch_plan(shipment_id: str) -> str:
    """Read a shipment plan and return its assigned hub."""
    plans = {
        "S-104": {"shipment_id": "S-104", "hub_code": "H-17"},
        "S-105": {"shipment_id": "S-105", "hub_code": "H-19"},
    }
    return json.dumps(plans.get(shipment_id, {"error": "shipment not found"}))


def lookup_hub_window(hub_code: str) -> str:
    """Read a hub window and return the weather station that governs it."""
    windows = {
        "H-17": {"cutoff": "17:22", "weather_station": "WX-LDS"},
        "H-19": {"cutoff": "16:55", "weather_station": "WX-MAN"},
    }
    return json.dumps({"hub_code": hub_code, **windows.get(hub_code, {})})


def lookup_weather_risk(weather_station: str) -> str:
    """Read the current risk band for a weather station."""
    risks = {"WX-LDS": "moderate", "WX-MAN": "low"}
    return json.dumps(
        {"weather_station": weather_station, "risk": risks.get(weather_station)}
    )


def exact_sequence(run, expected) -> bool:
    clean_executions = [
        execution
        for execution in (run.tools or [])
        if not execution.tool_call_error and not execution.is_paused
    ]
    if len(clean_executions) != len(expected):
        return False
    for execution, expected_step in zip(clean_executions, expected):
        if execution.tool_name != expected_step["tool"]:
            return False
        actual_arguments = dict(execution.tool_args or {})
        if not all(
            actual_arguments.get(key) == value
            for key, value in expected_step["arguments"].items()
        ):
            return False
    return True


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[read_dispatch_plan, lookup_hub_window, lookup_weather_risk],
    instructions=(
        "Calculate any routing recurrence exactly to select one shipment. Then use "
        "all three read-only tools in dependency order: read the chosen plan, use its "
        "returned hub for the window lookup, and use that returned weather station "
        "for the weather lookup. Ignore copied hub and station hints."
    ),
)

s104_sequence = [
    {"tool": "read_dispatch_plan", "arguments": {"shipment_id": "S-104"}},
    {"tool": "lookup_hub_window", "arguments": {"hub_code": "H-17"}},
    {
        "tool": "lookup_weather_risk",
        "arguments": {"weather_station": "WX-LDS"},
    },
]

env = Environment(
    name="multi-step-call-sequence",
    agent=agent,
    tasks=(
        Task(
            id="strict-chain",
            input=(
                "Assess shipment S-104. Read its plan, use the returned hub to read "
                "the window, then use the returned weather station to read risk."
            ),
            expected=s104_sequence,
        ),
        Task(
            id="route-by-eight",
            input=(
                "Duplicate scans point to S-104 and S-105; copied hints say H-19 and "
                "WX-MAN. Let a0=271828. For n=1 through 8, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. If a_8 is odd, "
                "assess S-104; otherwise assess S-105. Follow the returned plan, hub, "
                "and weather-station fields in dependency order."
            ),
            expected=s104_sequence,
        ),
        Task(
            id="route-by-nine",
            input=(
                "Duplicate scans point to S-104 and S-105; copied hints say H-19 and "
                "WX-MAN. Let a0=271828. For n=1 through 9, set "
                "a_n=(a_(n-1)^2 + 97*n + 31) mod 10000019. If a_9 is even, "
                "assess S-104; otherwise assess S-105. Follow the returned plan, hub, "
                "and weather-station fields in dependency order."
            ),
            expected=s104_sequence,
        ),
    ),
    scorer=CodeScorer(exact_sequence),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=6, concurrency=6)
    print(result)
    for task_result in result.task_results:
        print(
            f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored} "
            "matched the exact sequence"
        )
