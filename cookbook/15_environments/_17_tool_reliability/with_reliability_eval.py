"""
Tool Reliability - With ReliabilityEval
=======================================

ToolCallScorer builds the pass-rate grid. ReliabilityEval then inspects each
captured RunOutput with the same clean-execution and argument expectations.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.eval.reliability import ReliabilityEval
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer

_EXPECTED_CODE = 20944939


def submit_validation_code(code: int) -> str:
    """Submit the final integer validation code after completing the calculation."""
    return json.dumps({"received": True})


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[submit_validation_code],
    tool_call_limit=1,
    instructions=(
        "Compute the requested validation code yourself, then call "
        "submit_validation_code with the final integer."
    ),
)

env = Environment(
    name="tool-reliability-eval",
    agent=agent,
    tasks=(
        Task(
            id="checksum-submission",
            input=(
                "Compute 2718281828459045 times 1618033988749895. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "131071, subtract the product remainder modulo 65521, then submit "
                "that final integer as the validation code."
            ),
        ),
    ),
    scorer=ToolCallScorer(
        expected_tools=["submit_validation_code"],
        arguments={"submit_validation_code": {"code": _EXPECTED_CODE}},
    ),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=8)
    print(result)

    task_result = result.task_results[0]
    eval_passes = 0
    for attempt in task_result.attempts:
        if attempt.run is None:
            continue
        reliability = ReliabilityEval(
            agent_response=attempt.run,
            expected_tool_calls=["submit_validation_code"],
            expected_tool_call_arguments={
                "submit_validation_code": {"code": _EXPECTED_CODE}
            },
            allow_additional_tool_calls=True,
            show_spinner=False,
            telemetry=False,
        ).run()
        if reliability is not None and reliability.eval_status == "PASSED":
            eval_passes += 1
    print(
        f"{task_result.task.id}: scorer={task_result.n_passed}/{task_result.n_scored}, "
        f"reliability_eval={eval_passes}/{task_result.n_scored}"
    )
