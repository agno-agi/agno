"""
Execution Matching - Basic
==========================

Require both a clean validation-tool execution and the exact computed argument.
A fluent answer or a tool call with a plausible but wrong code does not pass.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
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
    name="execution-matching-basic",
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
    result.print_report()
