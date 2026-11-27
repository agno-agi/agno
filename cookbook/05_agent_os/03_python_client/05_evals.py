"""Run accuracy and reliability evaluations and eval suites through AgentOS.

The reliability case verifies the assistant calls the calculator's
``multiply`` tool with the expected arguments. The suite part lists and runs
the server's registered suite, once in the background, and runs cases posted
in the request.

Prerequisites: start ``_server.py`` and set OPENAI_API_KEY.
Run: .venvs/demo/bin/python cookbook/05_agent_os/03_python_client/05_evals.py
Try: compare the stored accuracy, reliability and suite result payloads.
"""

import asyncio

from agno.client import AgentOSClient
from agno.db.schemas.evals import EvalType
from agno.os.routers.evals.schemas import EvalSuiteCaseInput

BASE_URL = "http://localhost:7778"
AGENT_ID = "assistant"
SUITE_ID = "assistant-quality"


# ---------------------------------------------------------------------------
# Create the Client
# ---------------------------------------------------------------------------


async def run_eval_suites(client: AgentOSClient) -> None:
    """List and run the registered suite, then run cases posted in the request."""
    suites = await client.list_eval_suites()
    print(f"Registered suites: {[suite.id for suite in suites]}")
    suite = await client.get_eval_suite(SUITE_ID)
    print(f"{suite.name}: {len(suite.cases)} cases")

    smoke = await client.run_eval_suite(SUITE_ID, tag="smoke")
    print(f"Smoke run {smoke.id}: {smoke.eval_data['summary']}")

    # In the background the call returns at once; the run is polled until it is not RUNNING.
    background = await client.run_eval_suite(SUITE_ID, background=True)
    for _ in range(60):
        if background.eval_data["summary"]["status"] != "RUNNING":
            break
        await asyncio.sleep(2)
        background = await client.get_eval_run(background.id)
    else:
        raise TimeoutError("Background eval suite run did not finish")
    print(f"Background run {background.id}: {background.eval_data['summary']}")

    posted = await client.run_eval_suite_from_body(
        name="Posted checks",
        cases=[
            EvalSuiteCaseInput(
                name="adds",
                agent_id=AGENT_ID,
                input="Use the calculator to add 2 and 3.",
                expected_tool_calls=["add"],
            )
        ],
    )
    print(f"Posted run {posted.id}: {posted.eval_data['summary']}")


async def run_evaluations() -> None:
    """Run two evaluations, list and fetch their stored results, then run the eval suites."""
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

    for run_id in (accuracy.id, reliability.id):
        detail = await client.get_eval_run(run_id)
        print(f"Fetched {detail.id}: {detail.eval_type.value}")

    await run_eval_suites(client)


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_evaluations())
