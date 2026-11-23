"""
Execution Matching - Arguments
==============================

The tool succeeds for any integer, so name-only matching is too weak. Pin the
computed code while allowing an extra source argument on the real execution.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer

_EXPECTED_CODE = 20944939


def record_validation_code(code: int, source: str = "manual") -> str:
    """Record a validation code and optional source label for later review."""
    return json.dumps({"recorded": True, "code": code, "source": source})


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[record_validation_code],
    tool_call_limit=1,
    instructions=(
        "Compute the requested validation code yourself, then call "
        "record_validation_code with the final integer and source='calculation'."
    ),
)

env = Environment(
    name="argument-execution-matching",
    agent=agent,
    tasks=(
        Task(
            id="checksum-recording",
            input=(
                "Compute 2718281828459045 times 1618033988749895. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "131071, subtract the product remainder modulo 65521, then record "
                "that final integer as the validation code."
            ),
        ),
    ),
    scorer=ToolCallScorer(
        expected_tools=["record_validation_code"],
        arguments={"record_validation_code": {"code": _EXPECTED_CODE}},
    ),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=8)
    print(result)
    task_result = result.task_results[0]
    print(f"{task_result.task.id}: {task_result.n_passed}/{task_result.n_scored}")
