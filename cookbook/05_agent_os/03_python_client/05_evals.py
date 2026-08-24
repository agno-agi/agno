"""Run accuracy and reliability evaluations through AgentOS.

The reliability case verifies the assistant calls the calculator's
``multiply`` tool with the expected arguments.

Prerequisites: start ``_server.py`` and set OPENAI_API_KEY.
Run: .venvs/demo/bin/python cookbook/05_agent_os/03_python_client/05_evals.py
Try: compare the stored accuracy and reliability result payloads.
"""

import asyncio

from agno.client import AgentOSClient
from agno.db.schemas.evals import EvalType

BASE_URL = "http://localhost:7778"
AGENT_ID = "assistant"


# ---------------------------------------------------------------------------
# Create the Client
# ---------------------------------------------------------------------------


async def run_evaluations() -> None:
    """Run two evaluations, then list and fetch their stored results."""
    client = AgentOSClient(base_url=BASE_URL)

    accuracy = await client.run_eval(
        eval_type=EvalType.ACCURACY,
        input_text="What is 2 + 2?",
        agent_id=AGENT_ID,
        expected_output="4",
    )
    if accuracy is None:
        raise RuntimeError("Accuracy evaluation returned no result")
    print(f"Accuracy evaluation: {accuracy.id}")
    print(accuracy.eval_data)

    reliability = await client.run_eval(
        eval_type=EvalType.RELIABILITY,
        input_text="Use the calculator to multiply 10 by 5.",
        agent_id=AGENT_ID,
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    if reliability is None:
        raise RuntimeError("Reliability evaluation returned no result")
    print(f"Reliability evaluation: {reliability.id}")
    print(reliability.eval_data)

    eval_runs = await client.list_eval_runs(
        agent_id=AGENT_ID,
        eval_types=[EvalType.ACCURACY, EvalType.RELIABILITY],
    )
    print(f"Stored evaluations: {len(eval_runs.data)}")

    for eval_id in (accuracy.id, reliability.id):
        detail = await client.get_eval_run(eval_id)
        print(f"Fetched {detail.id}: {detail.eval_type.value}")


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_evaluations())
