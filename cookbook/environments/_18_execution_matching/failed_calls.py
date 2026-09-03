"""
Execution Matching - Failed Calls
=================================

The validation tool raises when the computed code is wrong. The request still
appears in the transcript, but an errored execution cannot satisfy the scorer.
"""

import json

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import ToolCallScorer

_EXPECTED_CODE = 20944939


def verify_validation_code(code: int) -> str:
    """Verify the final integer code; invalid codes raise instead of being accepted."""
    if code != _EXPECTED_CODE:
        raise ValueError("validation code rejected")
    return json.dumps({"verified": True})


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    tools=[verify_validation_code],
    tool_call_limit=1,
    instructions=(
        "Compute the requested validation code yourself, then call "
        "verify_validation_code once with the final integer."
    ),
)

env = Environment(
    name="failed-execution-matching",
    agent=agent,
    tasks=(
        Task(
            id="checksum-verification",
            input=(
                "Compute 2718281828459045 times 1618033988749895. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "131071, subtract the product remainder modulo 65521, then verify "
                "that final integer as the validation code."
            ),
        ),
    ),
    scorer=ToolCallScorer(expected_tools=["verify_validation_code"]),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=8)
    print(result)
    result.print_report()
