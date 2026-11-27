"""Ask Super Agent to run a slow workflow in the background, and keep talking while it runs.

Super Agent starts the workflow and answers at once with a receipt. The run goes on in its own
session. On each later message Super Agent is shown the state of the runs this conversation
started, so it says when one has finished and reads its result with check_background_run.

This example has no durable queue, so the run lives in the server's memory and is lost if the
server restarts. Pass AgentOS(queue=QueueConfig(durable=True)) with PostgreSQL to keep it.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_background_runs.py
"""

import asyncio
import time
from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from agno.workflow import Step, StepInput, StepOutput, Workflow
from fastapi.testclient import TestClient

SECONDS = 20
Path("tmp").mkdir(exist_ok=True)
db = SqliteDb(db_file=f"tmp/manager_background_runs_{int(time.time())}.db")


async def investigate(step_input: StepInput) -> StepOutput:
    await asyncio.sleep(SECONDS)
    return StepOutput(
        content="The nightly export fails because the job still uses the old IAM role."
    )


investigator = Workflow(
    id="investigator",
    name="Investigator",
    description="Investigates an incident. Takes a while.",
    db=db,
    steps=[Step(name="investigate", executor=investigate)],
)
agent_os = AgentOS(
    name="Background runs demo",
    db=db,
    workflows=[investigator],
    manager=OSManager(model=OpenAIResponses(id="gpt-5.6-luna"), access_docs=False),
    telemetry=False,
)
app = agent_os.get_app()


def ask(client: TestClient, message: str) -> None:
    started = time.monotonic()
    response = client.post(
        "/teams/superagent/runs",
        data={
            "message": message,
            "session_id": "demo-chat",
            "user_id": "sam",
            "stream": "false",
        },
    )
    response.raise_for_status()
    body = response.json()
    tools = [tool["tool_name"] for tool in body.get("tools") or []]
    print(f"\n> {message}")
    print(f"  {time.monotonic() - started:.1f}s, tools: {tools}")
    print("  " + (body.get("content") or "").replace("\n", "\n  "))


if __name__ == "__main__":
    with TestClient(app) as client:
        ask(
            client,
            "Run the Investigator on last night's export failure in the background. Do not wait for it.",
        )
        ask(client, "What is 17 times 23?")
        print(f"\nWaiting {SECONDS + 5} seconds for the Investigator to finish.")
        time.sleep(SECONDS + 5)
        ask(client, "Thanks. Anything else?")
